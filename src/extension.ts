import * as vscode from 'vscode';
import * as path from 'path';
import * as cp from 'child_process';
import * as fs from 'fs';

// =============================================================
// 1. Interfaces & Types (แก้ไขให้ตรงกับ actual_output.txt)
// =============================================================
interface PyGreenSenseIssue {
    file: string; // เพิ่มฟิลด์ file เข้ามา
    rule: string;
    message: string;
    lineno: number;
    end_lineno: number;
    severity: string;
}

interface CarbonReport {
    execution_details: { target_file: string; duration_seconds: number; };
    energy_and_emissions: {
        total_energy_consumed_kwh: number;
        carbon_emissions_kg_co2: number;
        emissions_rate_g_co2eq_per_kwh: number;
        country: string;
        region?: string;
    };
    code_metrics: { cosmic_function_points: number; total_loc_code_smells: number; };
    sci_metrics: { per_line_of_code_g_co2eq: number; per_cosmic_function_point_g_co2eq: number; };
    status: string;
    improvement_percent?: number;
}

interface WorkerResponse {
    status: string;
    data: {
        summary: any;
        results: PyGreenSenseIssue[]; // เปลี่ยนเป็น Array ให้ตรงกับ Python ส่งมา
        carbon_report?: CarbonReport;
    };
    message?: string;
}

// Global state
let currentPanel: vscode.WebviewPanel | undefined = undefined;

// =============================================================
// 2. Activate & Commands
// =============================================================
export function activate(context: vscode.ExtensionContext) {
    let disposable = vscode.commands.registerCommand('pygreensense.analyze', async () => {
        const editor = vscode.window.activeTextEditor;
        if (editor && editor.document.languageId === 'python') {
            await startFullProcess(editor.document, context);
        } else {
            vscode.window.showWarningMessage('Please open a Python file to analyze.');
        }
    });
    context.subscriptions.push(disposable);
}

// =============================================================
// 3. Main Workflow Orchestrator
// =============================================================
async function startFullProcess(document: vscode.TextDocument, context: vscode.ExtensionContext) {
    const pythonSourceDir = path.join(context.extensionPath, 'src', 'python_source');
    
    const pythonPath = await vscode.window.withProgress({
        location: vscode.ProgressLocation.Notification,
        title: "PyGreenSense: Checking Environment...",
        cancellable: false
    }, async (progress) => {
        return await ensureEnvironment(pythonSourceDir, progress);
    });

    if (!pythonPath) { return; } 

    await vscode.window.withProgress({
        location: vscode.ProgressLocation.Notification,
        title: "PyGreenSense: Analyzing Code & Carbon...",
        cancellable: false
    }, async (progress) => {
        const workerPath = path.join(pythonSourceDir, 'worker.py');
        const targetFile = document.fileName;
        
        try {
            const result = await runWorker(pythonPath, workerPath, targetFile);
            if (result.status === 'success') {
                showHtmlReport(result, context.extensionUri);
                vscode.window.showInformationMessage("Analysis Complete! 🌍");
            } else {
                vscode.window.showErrorMessage(`Analysis Error: ${result.message}`);
            }
        } catch (error: any) {
            vscode.window.showErrorMessage(`Critical Error: ${error.message}`);
        }
    });
}

// =============================================================
// 4. Environment Manager
// =============================================================
async function ensureEnvironment(sourceDir: string, progress: vscode.Progress<{ message?: string }>): Promise<string | null> {
    const venvPath = path.join(sourceDir, '.venv');
    const isWin = process.platform === 'win32';
    const pythonExec = isWin ? path.join(venvPath, 'Scripts', 'python.exe') : path.join(venvPath, 'bin', 'python');
    const pipExec = isWin ? path.join(venvPath, 'Scripts', 'pip.exe') : path.join(venvPath, 'bin', 'pip');

    if (!fs.existsSync(pythonExec)) {
        progress.report({ message: "Creating Virtual Environment..." });
        try {
            await execShell(`python -m venv "${venvPath}"`, sourceDir);
        } catch (e) {
            vscode.window.showErrorMessage("Failed to create .venv.");
            return null;
        }
    }

    try {
        await execShell(`"${pythonExec}" -c "import pygreensense_lib; import codecarbon"`, sourceDir);
    } catch (e) {
        progress.report({ message: "Installing dependencies..." });
        try {
            await execShell(`"${pipExec}" install -e .`, sourceDir);
        } catch (installError) {
            vscode.window.showErrorMessage("Failed to install dependencies.");
            return null;
        }
    }
    return pythonExec;
}

function execShell(cmd: string, cwd: string): Promise<string> {
    return new Promise((resolve, reject) => {
        cp.exec(cmd, { cwd: cwd }, (err, stdout, stderr) => {
            if (err) { reject(stderr || err.message); }
            else { resolve(stdout); }
        });
    });
}

// =============================================================
// 5. Worker Executor
// =============================================================
function runWorker(pythonPath: string, workerPath: string, targetFile: string): Promise<WorkerResponse> {
    return new Promise((resolve, reject) => {
        // 🌟 แก้ไข: ส่ง targetFile แทนการส่งโฟลเดอร์ทั้งหมด
        const args = [
            workerPath,
            targetFile, 
            '--carbon-run', targetFile
        ];

        // 🌟 แก้ไข: เพิ่ม maxBuffer เป็น 10MB ป้องกัน JSON ทะลัก
        cp.execFile(pythonPath, args, { cwd: path.dirname(workerPath), maxBuffer: 10 * 1024 * 1024 }, (err, stdout, stderr) => {
            try {
                const json = JSON.parse(stdout.trim());
                resolve(json);
            } catch (e) {
                console.error("Stdout:", stdout);
                console.error("Stderr:", stderr);
                reject(new Error("Failed to parse worker output. See Developer Console."));
            }
        });
    });
}

// =============================================================
// 6. HTML Report Generator (Webview)
// =============================================================
function showHtmlReport(data: WorkerResponse, extensionUri: vscode.Uri) {
    if (currentPanel) {
        currentPanel.reveal(vscode.ViewColumn.Two);
    } else {
        currentPanel = vscode.window.createWebviewPanel(
            'pyGreenSenseReport',
            '🌍 Green Analysis Report',
            vscode.ViewColumn.Two, 
            { enableScripts: true }
        );
        currentPanel.onDidDispose(() => { currentPanel = undefined; }, null, []);
    }
    currentPanel.webview.html = getWebviewContent(data);
}

function getWebviewContent(resp: WorkerResponse): string {
    const r = resp.data.carbon_report;
    const summary = resp.data.summary;
    
    // 🌟 แก้ไข: วนลูปอ่านข้อมูลแบบ Array ให้ตรงกับ actual_output.txt
    let issuesHtml = '';
    const results = resp.data.results;
    
    if (results && results.length > 0) {
        issuesHtml += `<table><thead><tr><th>File</th><th>Rule</th><th>Line</th><th>Message</th></tr></thead><tbody>`;
        results.forEach(i => {
            issuesHtml += `<tr>
                <td>${path.basename(i.file)}</td>
                <td><span class="badge warning">${i.rule}</span></td>
                <td>${i.lineno}</td>
                <td>${i.message}</td>
            </tr>`;
        });
        issuesHtml += `</tbody></table>`;
    } else {
        issuesHtml = '<p>✅ No Green Code Smells found!</p>';
    }

    let carbonHtml = '';
    if (r) {
        carbonHtml = `
            <div class="card-container">
                <div class="card">
                    <h2>${r.energy_and_emissions.carbon_emissions_kg_co2.toExponential(2)}</h2>
                    <p>kg CO2 (Total)</p>
                </div>
                <div class="card">
                    <h2>${r.sci_metrics.per_line_of_code_g_co2eq.toExponential(2)}</h2>
                    <p>gCO2 / LOC (SCI)</p>
                </div>
                <div class="card">
                    <h2>${r.status}</h2>
                    <p>Status</p>
                </div>
            </div>
            <div class="detail-box">
                <h3>⚡ Energy Details</h3>
                <ul>
                    <li><strong>Energy Consumed:</strong> ${r.energy_and_emissions.total_energy_consumed_kwh.toExponential(4)} kWh</li>
                    <li><strong>Emission Rate:</strong> ${r.energy_and_emissions.emissions_rate_g_co2eq_per_kwh.toFixed(4)} g/kWh</li>
                    <li><strong>Location:</strong> ${r.energy_and_emissions.country}</li>
                </ul>
            </div>
        `;
    } else {
        carbonHtml = `<div class="warning-box">⚠️ Carbon tracking disabled or failed.</div>`;
    }

    return `<!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <style>
            body { font-family: sans-serif; padding: 20px; background-color: var(--vscode-editor-background); color: var(--vscode-editor-foreground); }
            .card-container { display: flex; gap: 20px; margin-bottom: 20px; }
            .card { flex: 1; padding: 15px; background: var(--vscode-editor-lineHighlightBackground); border-radius: 8px; text-align: center; border: 1px solid var(--vscode-widget-border); }
            .card h2 { margin: 0; font-size: 1.5em; color: #4CAF50; }
            table { width: 100%; border-collapse: collapse; margin-top: 10px; }
            th, td { text-align: left; padding: 8px; border-bottom: 1px solid var(--vscode-widget-border); }
            .badge.warning { background-color: #ff9800; color: #000; padding: 2px 6px; border-radius: 4px; font-size: 0.8em; }
            .detail-box { background: var(--vscode-editor-inactiveSelectionBackground); padding: 15px; border-radius: 8px; margin-bottom: 20px; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🌍 PyGreenSense Report</h1>
            <p>Analysis of: <strong>${r ? r.execution_details.target_file : 'Unknown'}</strong></p>
            <hr>
            <h2>🌱 Carbon Footprint</h2>
            ${carbonHtml}
            <h2>🔍 Code Smells Analysis</h2>
            <div class="detail-box">
                <strong>Summary:</strong> Found ${summary.total_issues} issues in ${summary.total_files} file(s).
            </div>
            ${issuesHtml}
        </div>
    </body>
    </html>`;
}

export function deactivate() {}