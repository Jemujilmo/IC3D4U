import * as vscode from 'vscode';
import {
    buildCodegenPrompt,
    buildHistory,
    callDesignIntake,
    callLMStudio,
    canGenerateFromPlan,
    designPlanHistoryMessage,
    DesignIntakeResult,
} from './lmstudio';
import { saveAndDeploy } from './freecad';
import { DESIGN_INTAKE_PROMPT, SYSTEM_PROMPT } from './systemPrompt';

const PARTICIPANT_ID = 'ic3d4u.freecad';
let currentDesignPlan: DesignIntakeResult | undefined;

export function activate(context: vscode.ExtensionContext) {
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

async function handleRequest(
    request: vscode.ChatRequest,
    context: vscode.ChatContext,
    stream: vscode.ChatResponseStream,
    token: vscode.CancellationToken
): Promise<vscode.ChatResult> {

    // Handle the 'clear' slash command
    if (request.command === 'clear') {
        currentDesignPlan = undefined;
        stream.markdown('History cleared. Start a new part description.');
        return {};
    }

    stream.progress('Planning design intent via LM Studio...');

    const history = buildHistory(context.history);
    const intakeHistory = currentDesignPlan
        ? [...history, designPlanHistoryMessage(currentDesignPlan)]
        : history;

    let plan: DesignIntakeResult;
    try {
        const result = await callDesignIntake(
            request.prompt,
            intakeHistory,
            DESIGN_INTAKE_PROMPT,
            token
        );
        plan = result.plan;
    } catch (err: any) {
        stream.markdown(
            `**Error:** ${err.message}\n\n` +
            `Make sure LM Studio is running and the server is started at \`http://localhost:1234\`.\n\n` +
            `You can change the URL in **Settings → IC3D4U FreeCAD Agent**.`
        );
        return { errorDetails: { message: err.message } };
    }

    currentDesignPlan = plan;

    if (!canGenerateFromPlan(plan)) {
        stream.markdown(formatIntakeQuestions(plan));
        return { metadata: { designIntakePlan: plan } };
    }

    stream.progress('Generating FreeCAD script from normalized spec...');

    let code: string;
    try {
        const result = await callLMStudio(
            buildCodegenPrompt(plan),
            history,
            SYSTEM_PROMPT,
            token
        );
        code = result.code;
    } catch (err: any) {
        stream.markdown(
            `**Error:** ${err.message}\n\n` +
            `Make sure LM Studio is running and the server is started at \`http://localhost:1234\`.\n\n` +
            `You can change the URL in **Settings → IC3D4U FreeCAD Agent**.`
        );
        return { errorDetails: { message: err.message } };
    }

    // Stream the generated code to the chat
    stream.markdown('**Generated FreeCAD Script:**\n\n');
    stream.markdown('```python\n' + code + '\n```\n\n');

    // Save and deploy to FreeCAD macro folder
    let deployed: ReturnType<typeof saveAndDeploy>;
    try {
        deployed = saveAndDeploy(code);
    } catch (err: any) {
        stream.markdown(`⚠️ Could not save macro: ${err.message}`);
        return {};
    }

    if (deployed.macroPath) {
        stream.markdown(
            `✅ **Macro saved** → \`${deployed.macroPath}\`\n\n` +
            `The watcher will auto-execute it in FreeCAD instantly.\n\n` +
            `If the watcher isn't running: **Macro menu → Macros → generated\\_part → Execute**`
        );
    } else {
        stream.markdown(
            `⚠️ **FreeCAD macro folder not found.**\n\n` +
            `Copy the code above and paste it into FreeCAD's Python Console:\n` +
            `**View → Panels → Python Console**\n\n` +
            `Or set the correct path in **Settings → IC3D4U → FreeCAD Macro Dir**.`
        );
    }

    if (deployed.versionFile) {
        const name = deployed.versionFile.split(/[/\\]/).pop();
        stream.markdown(`\n📁 Version saved: \`output/parts/${name}\``);
    }

    return {};
}

function formatIntakeQuestions(plan: DesignIntakeResult): string {
    const lines: string[] = [];
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

export function deactivate() {}
