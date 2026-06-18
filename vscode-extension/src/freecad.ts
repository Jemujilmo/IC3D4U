import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';

function getMacroDir(): string {
    const override = vscode.workspace
        .getConfiguration('ic3d4u')
        .get<string>('freecadMacroDir', '');

    if (override && override.trim()) {
        return override.trim();
    }

    // Auto-detect FreeCAD 1.x macro directory on Windows
    const appData = process.env.APPDATA ?? path.join(os.homedir(), 'AppData', 'Roaming');
    const candidates = [
        path.join(appData, 'FreeCAD', 'v1-1', 'Macro'),
        path.join(appData, 'FreeCAD', 'v1-0', 'Macro'),
        path.join(appData, 'FreeCAD', 'Macro'),
    ];

    for (const candidate of candidates) {
        if (fs.existsSync(candidate)) {
            return candidate;
        }
    }

    return '';
}

function getOutputDir(): string | undefined {
    const folders = vscode.workspace.workspaceFolders;
    return folders ? path.join(folders[0].uri.fsPath, 'output') : undefined;
}

export interface DeployResult {
    macroPath: string | null;
    versionFile: string | null;
}

export function saveAndDeploy(code: string): DeployResult {
    const result: DeployResult = { macroPath: null, versionFile: null };

    // Save to workspace output + versioned parts
    const outputDir = getOutputDir();
    if (outputDir) {
        fs.mkdirSync(outputDir, { recursive: true });
        fs.writeFileSync(path.join(outputDir, 'generated_part.py'), code, 'utf8');

        const partsDir = path.join(outputDir, 'parts');
        fs.mkdirSync(partsDir, { recursive: true });
        const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
        const versionFile = path.join(partsDir, `part_${ts}.py`);
        fs.writeFileSync(versionFile, code, 'utf8');
        result.versionFile = versionFile;
    }

    // Deploy to FreeCAD macro folder
    const macroDir = getMacroDir();
    if (macroDir) {
        const macroFile = path.join(macroDir, 'generated_part.FCMacro');
        fs.writeFileSync(macroFile, code, 'utf8');
        result.macroPath = macroFile;
    }

    return result;
}
