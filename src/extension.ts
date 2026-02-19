// Import VS Code extension API for commands, editors, webviews, and progress notifications
import * as vscode from 'vscode';
// Import Node.js path module for constructing cross-platform file paths
import * as path from 'path';
// Import Node.js child_process module for spawning shell commands and Python processes
import * as cp from 'child_process';
// Import Node.js filesystem module for checking if files/directories exist
import * as fs from 'fs';

// =============================================================
// 1. Interfaces & Types
//    TypeScript interfaces that mirror the JSON structure returned
//    by the Python worker process (worker.py).
// =============================================================

/** Represents a single code smell issue detected by PyGreenSense analysis. */
interface PyGreenSenseIssue {
    file: string;       // Absolute path to the file where the issue was found
    rule: string;       // Rule name that triggered this issue (e.g., "GodClass", "LongMethod")
    message: string;    // Human-readable description of the issue
    lineno: number;     // Starting line number of the problematic code
    end_lineno: number; // Ending line number of the problematic code
    severity: string;   // Severity level: "High", "Medium", or "Warning"
}

/** Represents carbon emission and energy metrics from CodeCarbon tracking. */
interface CarbonReport {
    execution_details: { target_file: string; duration_seconds: number; }; // Which file was run and how long it took
    energy_and_emissions: {
        total_energy_consumed_kwh: number;       // Total energy consumed in kilowatt-hours
        carbon_emissions_kg_co2: number;         // Total CO2 emissions in kilograms
        emissions_rate_g_co2eq_per_kwh: number;  // Carbon intensity of the electricity grid (gCO2eq/kWh)
        country: string;                         // Country where the run was executed
        region?: string;                         // Optional region/state within the country
    };
    code_metrics: { cosmic_function_points: number; total_loc_code_smells: number; }; // COSMIC CFP and code smell LOC
    sci_metrics: { per_line_of_code_g_co2eq: number; per_cosmic_function_point_g_co2eq: number; }; // SCI scores
    status: string;              // "Initial", "Greener", "Hotter", or "Normal"
    improvement_percent?: number; // Percentage improvement compared to previous run (null if first run)
}

/** Top-level response envelope returned by worker.py via stdout JSON. */
interface WorkerResponse {
    status: string; // "success" or "error"
    data: {
        summary: any;                    // Contains total_files, total_issues, total_smell_loc
        results: PyGreenSenseIssue[];    // Flat array of all code smell issues across all files
        carbon_report?: CarbonReport;    // Carbon tracking results (undefined if tracking failed/disabled)
    };
    message?: string; // Error message when status is "error"
}

// Global state: holds a reference to the currently open webview panel so we can
// reuse it instead of opening a new one every time the user runs an analysis.
let currentPanel: vscode.WebviewPanel | undefined = undefined;

// =============================================================
// 2. Activate & Commands
// =============================================================
/**
 * Activates the PyGreenSense extension.
 * Registers the 'pygreensense.analyze' command which triggers code smell
 * and carbon emission analysis on the currently open Python file.
 * @param context - The VS Code extension context used for managing subscriptions.
 */
export function activate(context: vscode.ExtensionContext) {
    // Register the 'pygreensense.analyze' command that users invoke from the Command Palette
    let disposable = vscode.commands.registerCommand('pygreensense.analyze', async () => {
        // Get the currently active text editor in VS Code
        const editor = vscode.window.activeTextEditor;
        // Only proceed if there is an active editor and it contains a Python file
        if (editor && editor.document.languageId === 'python') {
            // Launch the full analysis pipeline on the active Python document
            await startFullProcess(editor.document, context);
        } else {
            // Warn the user if no Python file is open
            vscode.window.showWarningMessage('Please open a Python file to analyze.');
        }
    });
    // Add the command to subscriptions so it is properly disposed when the extension deactivates
    context.subscriptions.push(disposable);
}

// =============================================================
// 3. Main Workflow Orchestrator
// =============================================================
/**
 * Orchestrates the entire analysis workflow: environment setup, code smell
 * detection, carbon tracking, and report generation.
 * Shows progress notifications to the user during each phase.
 * @param document - The active Python document to analyze.
 * @param context - The VS Code extension context for accessing extension paths.
 */
async function startFullProcess(document: vscode.TextDocument, context: vscode.ExtensionContext) {
    // Build the absolute path to the Python source directory bundled with the extension
    const pythonSourceDir = path.join(context.extensionPath, 'src', 'python_source');
    
    // Phase 1: Ensure the Python virtual environment and dependencies are ready.
    // Show a non-cancellable progress notification while checking/creating the environment.
    const pythonPath = await vscode.window.withProgress({
        location: vscode.ProgressLocation.Notification,
        title: "PyGreenSense: Checking Environment...",
        cancellable: false
    }, async (progress) => {
        // Delegate to ensureEnvironment() which creates venv and installs deps if needed
        return await ensureEnvironment(pythonSourceDir, progress);
    });

    // If environment setup failed (returned null), abort the analysis
    if (!pythonPath) { return; } 

    // Phase 2: Run the actual code smell + carbon analysis.
    // Show a progress notification while the Python worker is executing.
    await vscode.window.withProgress({
        location: vscode.ProgressLocation.Notification,
        title: "PyGreenSense: Analyzing Code & Carbon...",
        cancellable: false
    }, async (progress) => {
        // Build the path to the worker.py script that orchestrates the Python-side analysis
        const workerPath = path.join(pythonSourceDir, 'worker.py');
        // Get the absolute file path of the Python document the user has open
        const targetFile = document.fileName;
        
        try {
            // Spawn the Python worker process and wait for its JSON result
            const result = await runWorker(pythonPath, workerPath, targetFile);
            if (result.status === 'success') {
                // On success, render the HTML report in a webview panel
                showHtmlReport(result, context.extensionUri);
                // Show a brief success notification to the user
                vscode.window.showInformationMessage("Analysis Complete! 🌍");
            } else {
                // On analysis-level error, show the error message from the worker
                vscode.window.showErrorMessage(`Analysis Error: ${result.message}`);
            }
        } catch (error: any) {
            // On critical error (e.g., worker crashed, JSON parse failed), show error
            vscode.window.showErrorMessage(`Critical Error: ${error.message}`);
        }
    });
}

// =============================================================
// 4. Environment Manager
// =============================================================
/**
 * Ensures the Python virtual environment exists and all required dependencies
 * (pygreensense_lib, codecarbon) are installed. Creates the venv and runs
 * `pip install -e .` if needed.
 * @param sourceDir - The directory containing the Python source and pyproject.toml.
 * @param progress - VS Code progress reporter for displaying status messages.
 * @returns The absolute path to the Python executable inside the venv, or null on failure.
 */
async function ensureEnvironment(sourceDir: string, progress: vscode.Progress<{ message?: string }>): Promise<string | null> {
    // Build path to the virtual environment directory (.venv) inside the Python source folder
    const venvPath = path.join(sourceDir, '.venv');
    // Detect if running on Windows to use the correct executable paths
    const isWin = process.platform === 'win32';
    // Resolve the Python executable path inside the venv (platform-specific location)
    const pythonExec = isWin ? path.join(venvPath, 'Scripts', 'python.exe') : path.join(venvPath, 'bin', 'python');
    // Resolve the pip executable path inside the venv (platform-specific location)
    const pipExec = isWin ? path.join(venvPath, 'Scripts', 'pip.exe') : path.join(venvPath, 'bin', 'pip');

    // Check if the venv already exists by looking for the Python executable
    if (!fs.existsSync(pythonExec)) {
        // Venv does not exist yet — create it
        progress.report({ message: "Creating Virtual Environment..." });
        try {
            // Run `python -m venv` to create a new virtual environment
            await execShell(`python -m venv "${venvPath}"`, sourceDir);
        } catch (e) {
            // If venv creation fails, show error and return null to abort
            vscode.window.showErrorMessage("Failed to create .venv.");
            return null;
        }
    }

    // Verify that the required packages (pygreensense_lib and codecarbon) are importable
    try {
        // Attempt to import both libraries — if this succeeds, deps are already installed
        await execShell(`"${pythonExec}" -c "import pygreensense_lib; import codecarbon"`, sourceDir);
    } catch (e) {
        // Import failed — need to install dependencies
        progress.report({ message: "Installing dependencies..." });
        try {
            // Run `pip install -e .` to install the package in editable mode from pyproject.toml
            await execShell(`"${pipExec}" install -e .`, sourceDir);
        } catch (installError) {
            // If installation fails, show error and return null to abort
            vscode.window.showErrorMessage("Failed to install dependencies.");
            return null;
        }
    }
    // Return the validated path to the Python executable for use by the worker
    return pythonExec;
}

/**
 * Executes a shell command in a given working directory and returns its stdout.
 * @param cmd - The shell command to execute.
 * @param cwd - The working directory in which to run the command.
 * @returns A promise that resolves with stdout on success, or rejects with stderr on failure.
 */
function execShell(cmd: string, cwd: string): Promise<string> {
    // Wrap Node.js cp.exec in a Promise for async/await usage
    return new Promise((resolve, reject) => {
        // Execute the shell command in the specified working directory
        cp.exec(cmd, { cwd: cwd }, (err, stdout, stderr) => {
            // If the command returned an error, reject with stderr (or the error message)
            if (err) { reject(stderr || err.message); }
            // Otherwise resolve with the captured standard output
            else { resolve(stdout); }
        });
    });
}

// =============================================================
// 5. Worker Executor
// =============================================================
/**
 * Spawns the Python worker process (worker.py) that performs code smell
 * analysis and carbon emission tracking on the target file.
 * Parses the JSON output from stdout into a WorkerResponse object.
 * @param pythonPath - Absolute path to the Python executable in the venv.
 * @param workerPath - Absolute path to the worker.py script.
 * @param targetFile - Absolute path to the Python file to be analyzed.
 * @returns A promise that resolves with the parsed WorkerResponse JSON.
 */
function runWorker(pythonPath: string, workerPath: string, targetFile: string): Promise<WorkerResponse> {
    // Wrap cp.execFile in a Promise for async/await usage
    return new Promise((resolve, reject) => {
        // Build the argument list for worker.py:
        // argv[1] = target file path (for code smell analysis)
        // argv[2..3] = --carbon-run <file> (tells worker to also run carbon tracking on this file)
        const args = [
            workerPath,
            targetFile, 
            '--carbon-run', targetFile
        ];

        // Spawn the Python process with a 10 MB stdout buffer to handle large JSON output
        cp.execFile(pythonPath, args, { cwd: path.dirname(workerPath), maxBuffer: 10 * 1024 * 1024 }, (err, stdout, stderr) => {
            try {
                // Parse the JSON string printed by worker.py to stdout
                const json = JSON.parse(stdout.trim());
                // Return the parsed WorkerResponse object
                resolve(json);
            } catch (e) {
                // If JSON parsing fails, log raw output to Developer Console for debugging
                console.error("Stdout:", stdout);
                console.error("Stderr:", stderr);
                // Reject with a user-friendly error pointing to the Developer Console
                reject(new Error("Failed to parse worker output. See Developer Console."));
            }
        });
    });
}

// =============================================================
// 6. HTML Report Generator (Webview)
// =============================================================
/**
 * Creates or reveals a VS Code Webview panel to display the analysis report.
 * Reuses an existing panel if one is already open.
 * @param data - The full worker response containing code smell and carbon data.
 * @param extensionUri - The URI of the extension, used for webview resource resolution.
 */
function showHtmlReport(data: WorkerResponse, extensionUri: vscode.Uri) {
    // If a webview panel is already open, bring it to the foreground instead of creating a new one
    if (currentPanel) {
        currentPanel.reveal(vscode.ViewColumn.Two);
    } else {
        // Create a new webview panel in the second editor column
        currentPanel = vscode.window.createWebviewPanel(
            'pyGreenSenseReport',          // Internal panel type identifier
            '🌍 Green Analysis Report',      // Title shown on the panel tab
            vscode.ViewColumn.Two,          // Display in the second column (side-by-side with code)
            { enableScripts: true }         // Allow JavaScript execution inside the webview
        );
        // When the user closes the panel, reset the global reference so a new one can be created next time  
        currentPanel.onDidDispose(() => { currentPanel = undefined; }, null, []);
    }
    // Generate the full HTML content and set it as the webview's HTML body
    currentPanel.webview.html = getWebviewContent(data);
}

/**
 * Generates the full HTML content for the analysis report webview.
 * Renders carbon footprint metrics (energy, emissions, SCI) as summary cards
 * and code smell issues as a sortable table.
 * @param resp - The worker response containing summary, issues, and carbon report data.
 * @returns A complete HTML document string ready to be rendered in the webview.
 */
function getWebviewContent(resp: WorkerResponse): string {
    // Extract the carbon report and summary objects from the response for convenience
    const r = resp.data.carbon_report;
    const summary = resp.data.summary;
    
    // --- Build the Issues HTML Table ---
    // Iterate over the flat results array and render each issue as a table row
    let issuesHtml = '';
    const results = resp.data.results;
    
    if (results && results.length > 0) {
        // Start the HTML table with column headers: File, Rule, Line, Message
        issuesHtml += `<table><thead><tr><th>File</th><th>Rule</th><th>Line</th><th>Message</th></tr></thead><tbody>`;
        // Render one row per code smell issue
        results.forEach(i => {
            issuesHtml += `<tr>
                <td>${path.basename(i.file)}</td>
                <td><span class="badge warning">${i.rule}</span></td>
                <td>${i.lineno}</td>
                <td>${i.message}</td>
            </tr>`;
        });
        // Close the table body and table tags
        issuesHtml += `</tbody></table>`;
    } else {
        // No issues found — show a congratulatory message
        issuesHtml = '<p>✅ No Green Code Smells found!</p>';
    }

    // --- Build the Carbon Metrics HTML ---
    let carbonHtml = '';
    if (r) {
        // Carbon data is available — render three summary cards and an energy details box
        carbonHtml = `
            <div class="card-container">
                <div class="card">
                    <!-- Card 1: Total carbon emissions in scientific notation -->
                    <h2>${r.energy_and_emissions.carbon_emissions_kg_co2.toExponential(2)}</h2>
                    <p>kg CO2 (Total)</p>
                </div>
                <div class="card">
                    <!-- Card 2: SCI metric — grams of CO2 per line of code -->
                    <h2>${r.sci_metrics.per_line_of_code_g_co2eq.toExponential(2)}</h2>
                    <p>gCO2 / LOC (SCI)</p>
                </div>
                <div class="card">
                    <!-- Card 3: Overall green status (Initial/Greener/Hotter/Normal) -->
                    <h2>${r.status}</h2>
                    <p>Status</p>
                </div>
            </div>
            <div class="detail-box">
                <h3>⚡ Energy Details</h3>
                <ul>
                    <!-- Detailed energy consumption, emission rate, and location -->
                    <li><strong>Energy Consumed:</strong> ${r.energy_and_emissions.total_energy_consumed_kwh.toExponential(4)} kWh</li>
                    <li><strong>Emission Rate:</strong> ${r.energy_and_emissions.emissions_rate_g_co2eq_per_kwh.toFixed(4)} g/kWh</li>
                    <li><strong>Location:</strong> ${r.energy_and_emissions.country}</li>
                </ul>
            </div>
        `;
    } else {
        // No carbon data — show a warning that tracking was disabled or failed
        carbonHtml = `<div class="warning-box">⚠️ Carbon tracking disabled or failed.</div>`;
    }

    // --- Assemble the complete HTML document ---
    // Uses VS Code CSS variables (--vscode-*) to match the user's current theme
    return `<!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <style>
            /* Base styles using VS Code theme variables for seamless integration */
            body { font-family: sans-serif; padding: 20px; background-color: var(--vscode-editor-background); color: var(--vscode-editor-foreground); }
            /* Flexbox container for the three summary cards */
            .card-container { display: flex; gap: 20px; margin-bottom: 20px; }
            /* Individual card styling with themed background and border */
            .card { flex: 1; padding: 15px; background: var(--vscode-editor-lineHighlightBackground); border-radius: 8px; text-align: center; border: 1px solid var(--vscode-widget-border); }
            /* Green accent color for card headings */
            .card h2 { margin: 0; font-size: 1.5em; color: #4CAF50; }
            /* Full-width table with collapsed borders */
            table { width: 100%; border-collapse: collapse; margin-top: 10px; }
            th, td { text-align: left; padding: 8px; border-bottom: 1px solid var(--vscode-widget-border); }
            /* Orange badge for rule names to draw attention */
            .badge.warning { background-color: #ff9800; color: #000; padding: 2px 6px; border-radius: 4px; font-size: 0.8em; }
            /* Detail box with subtle background for energy and summary sections */
            .detail-box { background: var(--vscode-editor-inactiveSelectionBackground); padding: 15px; border-radius: 8px; margin-bottom: 20px; }
        </style>
    </head>
    <body>
        <div class="container">
            <!-- Report header with the analyzed file name -->
            <h1>🌍 PyGreenSense Report</h1>
            <p>Analysis of: <strong>${r ? r.execution_details.target_file : 'Unknown'}</strong></p>
            <hr>
            <!-- Carbon footprint section with cards and details -->
            <h2>🌱 Carbon Footprint</h2>
            ${carbonHtml}
            <!-- Code smells section with summary count and issue table -->
            <h2>🔍 Code Smells Analysis</h2>
            <div class="detail-box">
                <strong>Summary:</strong> Found ${summary.total_issues} issues in ${summary.total_files} file(s).
            </div>
            ${issuesHtml}
        </div>
    </body>
    </html>`;
}

/**
 * Deactivates the PyGreenSense extension.
 * Called by VS Code when the extension is being unloaded. Currently a no-op.
 */
export function deactivate() {}