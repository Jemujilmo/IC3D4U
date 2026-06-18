"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
exports.saveAndDeploy = saveAndDeploy;
const vscode = __importStar(require("vscode"));
const fs = __importStar(require("fs"));
const path = __importStar(require("path"));
const os = __importStar(require("os"));
function getMacroDir() {
    const override = vscode.workspace
        .getConfiguration('ic3d4u')
        .get('freecadMacroDir', '');
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
function getOutputDir() {
    const folders = vscode.workspace.workspaceFolders;
    return folders ? path.join(folders[0].uri.fsPath, 'output') : undefined;
}
function saveAndDeploy(code) {
    const result = { macroPath: null, versionFile: null };
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
//# sourceMappingURL=freecad.js.map