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
exports.activate = activate;
exports.deactivate = deactivate;
const vscode = __importStar(require("vscode"));
const lmstudio_1 = require("./lmstudio");
const freecad_1 = require("./freecad");
const systemPrompt_1 = require("./systemPrompt");
const PARTICIPANT_ID = 'ic3d4u.freecad';
let currentDesignPlan;
function activate(context) {
    const participant = vscode.chat.createChatParticipant(PARTICIPANT_ID, handleRequest);
    // Use a built-in icon that works without an image file
    participant.iconPath = new vscode.ThemeIcon('circuit-board');
    participant.followupProvider = {
        provideFollowups(_result, _context, _token) {
            return [
                {
                    prompt: 'add a 5mm fillet to all top edges',
                    label: '$(symbol-misc) Add fillet',
                    participant: PARTICIPANT_ID,
                },
                {
                    prompt: 'add 4 bolt holes at the corners',
                    label: '$(circle-outline) Add bolt holes',
                    participant: PARTICIPANT_ID,
                },
                {
                    prompt: 'export this part as STL',
                    label: '$(export) Export instructions',
                    participant: PARTICIPANT_ID,
                },
            ];
        },
    };
    context.subscriptions.push(participant);
}
async function handleRequest(request, context, stream, token) {
    // Handle the 'clear' slash command
    if (request.command === 'clear') {
        currentDesignPlan = undefined;
        stream.markdown('History cleared. Start a new part description.');
        return {};
    }
    stream.progress('Planning design intent via LM Studio...');
    const history = (0, lmstudio_1.buildHistory)(context.history);
    const intakeHistory = currentDesignPlan
        ? [...history, (0, lmstudio_1.designPlanHistoryMessage)(currentDesignPlan)]
        : history;
    let plan;
    try {
        const result = await (0, lmstudio_1.callDesignIntake)(request.prompt, intakeHistory, systemPrompt_1.DESIGN_INTAKE_PROMPT, token);
        plan = result.plan;
    }
    catch (err) {
        stream.markdown(`**Error:** ${err.message}\n\n` +
            `Make sure LM Studio is running and the server is started at \`http://localhost:1234\`.\n\n` +
            `You can change the URL in **Settings → IC3D4U FreeCAD Agent**.`);
        return { errorDetails: { message: err.message } };
    }
    currentDesignPlan = plan;
    if (!(0, lmstudio_1.canGenerateFromPlan)(plan)) {
        stream.markdown(formatIntakeQuestions(plan));
        return { metadata: { designIntakePlan: plan } };
    }
    stream.progress('Generating FreeCAD script from normalized spec...');
    let code;
    try {
        const result = await (0, lmstudio_1.callLMStudio)((0, lmstudio_1.buildCodegenPrompt)(plan), history, systemPrompt_1.SYSTEM_PROMPT, token);
        code = result.code;
    }
    catch (err) {
        stream.markdown(`**Error:** ${err.message}\n\n` +
            `Make sure LM Studio is running and the server is started at \`http://localhost:1234\`.\n\n` +
            `You can change the URL in **Settings → IC3D4U FreeCAD Agent**.`);
        return { errorDetails: { message: err.message } };
    }
    // Stream the generated code to the chat
    stream.markdown('**Generated FreeCAD Script:**\n\n');
    stream.markdown('```python\n' + code + '\n```\n\n');
    // Save and deploy to FreeCAD macro folder
    let deployed;
    try {
        deployed = (0, freecad_1.saveAndDeploy)(code);
    }
    catch (err) {
        stream.markdown(`⚠️ Could not save macro: ${err.message}`);
        return {};
    }
    if (deployed.macroPath) {
        stream.markdown(`✅ **Macro saved** → \`${deployed.macroPath}\`\n\n` +
            `The watcher will auto-execute it in FreeCAD instantly.\n\n` +
            `If the watcher isn't running: **Macro menu → Macros → generated\\_part → Execute**`);
    }
    else {
        stream.markdown(`⚠️ **FreeCAD macro folder not found.**\n\n` +
            `Copy the code above and paste it into FreeCAD's Python Console:\n` +
            `**View → Panels → Python Console**\n\n` +
            `Or set the correct path in **Settings → IC3D4U → FreeCAD Macro Dir**.`);
    }
    if (deployed.versionFile) {
        const name = deployed.versionFile.split(/[/\\]/).pop();
        stream.markdown(`\n📁 Version saved: \`output/parts/${name}\``);
    }
    return {};
}
function formatIntakeQuestions(plan) {
    const lines = [];
    lines.push(plan.userMessage || 'I need a little more detail before generating CAD.');
    lines.push('');
    if (plan.questions.length === 0) {
        lines.push('Please add the missing design details and I will try again.');
        return lines.join('\n');
    }
    for (const [index, question] of plan.questions.entries()) {
        lines.push(`${index + 1}. ${question.text}`);
        lines.push(`   id: \`${question.id}\`, expects: \`${question.expects}\``);
        if (question.choices && question.choices.length > 0) {
            lines.push(`   choices: ${question.choices.map(choice => `\`${choice}\``).join(', ')}`);
        }
        if (question.examples && question.examples.length > 0) {
            lines.push(`   examples: ${question.examples.map(example => `\`${example}\``).join(', ')}`);
        }
    }
    return lines.join('\n');
}
function deactivate() { }
//# sourceMappingURL=extension.js.map