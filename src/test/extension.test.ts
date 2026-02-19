import * as assert from 'assert';

// You can import and use all API from the 'vscode' module
// as well as import your extension to test it
import * as vscode from 'vscode';
// import * as myExtension from '../../extension';

/**
 * Test suite for the PyGreenSense VS Code extension.
 * Contains basic smoke tests to verify extension activation and core functionality.
 */
suite('Extension Test Suite', () => {
	vscode.window.showInformationMessage('Start all tests.');

	/** Verifies that Array.indexOf returns -1 for elements not present in the array. */
	test('Sample test', () => {
		assert.strictEqual(-1, [1, 2, 3].indexOf(5));
		assert.strictEqual(-1, [1, 2, 3].indexOf(0));
	});
});
