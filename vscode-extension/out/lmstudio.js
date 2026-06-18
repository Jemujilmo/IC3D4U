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
exports.callLMStudio = callLMStudio;
exports.callDesignIntake = callDesignIntake;
exports.canGenerateFromPlan = canGenerateFromPlan;
exports.buildCodegenPrompt = buildCodegenPrompt;
exports.designPlanHistoryMessage = designPlanHistoryMessage;
exports.buildHistory = buildHistory;
const vscode = __importStar(require("vscode"));
function extractCode(text) {
    const match = text.match(/```(?:python)?\s*\n([\s\S]*?)```/);
    return match ? match[1].trim() : text.trim();
}
function getConfig() {
    const cfg = vscode.workspace.getConfiguration('ic3d4u');
    return {
        baseUrl: cfg.get('lmStudioUrl', 'http://localhost:1234/v1'),
        model: cfg.get('modelName', 'qwen3-coder-30b-a3b-instruct'),
        maxTokens: cfg.get('maxTokens', 3000),
    };
}
async function postChatCompletion(messages, token) {
    const { baseUrl, model, maxTokens } = getConfig();
    const controller = new AbortController();
    token.onCancellationRequested(() => controller.abort());
    let response;
    try {
        response = await fetch(`${baseUrl}/chat/completions`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                model,
                messages,
                temperature: 0.1,
                max_tokens: maxTokens,
                stream: false,
            }),
            signal: controller.signal,
        });
    }
    catch (err) {
        if (err.name === 'AbortError') {
            throw new Error('Cancelled');
        }
        throw new Error(`Cannot reach LM Studio at ${baseUrl}. Make sure the server is started.`);
    }
    if (!response.ok) {
        throw new Error(`LM Studio responded with HTTP ${response.status}`);
    }
    const data = (await response.json());
    return data.choices[0].message.content;
}
async function callLMStudio(prompt, history, systemPrompt, token) {
    const messages = [
        { role: 'system', content: systemPrompt },
        ...history,
        { role: 'user', content: prompt },
    ];
    const raw = await postChatCompletion(messages, token);
    const code = extractCode(raw);
    return { code, raw };
}
async function callDesignIntake(prompt, history, systemPrompt, token) {
    const messages = [
        { role: 'system', content: systemPrompt },
        ...history,
        { role: 'user', content: prompt },
    ];
    const raw = await postChatCompletion(messages, token);
    const parsed = extractJson(raw);
    return { plan: normalizeDesignIntakeResult(parsed), raw };
}
function canGenerateFromPlan(plan) {
    return (plan.action === 'proceed'
        && (plan.readiness === 'ready' || plan.readiness === 'assumptions_allowed')
        && typeof plan.normalizedSpec === 'object'
        && plan.normalizedSpec !== null);
}
function buildCodegenPrompt(plan) {
    return ('Generate a complete FreeCAD Python script from this normalized design spec. ' +
        'Use the JSON as the source of truth and follow the system output rules.\n\n' +
        `NORMALIZED_SPEC_JSON:\n${JSON.stringify(plan.normalizedSpec, null, 2)}`);
}
function designPlanHistoryMessage(plan) {
    return {
        role: 'assistant',
        content: 'Previous design intake result JSON:\n' + JSON.stringify(plan, null, 2),
    };
}
function buildHistory(history) {
    const messages = [];
    for (const turn of history) {
        if (turn instanceof vscode.ChatRequestTurn) {
            messages.push({ role: 'user', content: turn.prompt });
        }
        else if (turn instanceof vscode.ChatResponseTurn) {
            const text = turn.response
                .filter((p) => p instanceof vscode.ChatResponseMarkdownPart)
                .map(p => p.value.value)
                .join('');
            if (text.trim()) {
                messages.push({ role: 'assistant', content: text });
            }
        }
    }
    // Keep last 3 turns (6 messages) to stay within context budget
    return messages.slice(-6);
}
function extractJson(text) {
    let stripped = text.trim();
    const fenced = stripped.match(/```(?:json)?\s*\n([\s\S]*?)```/);
    if (fenced) {
        stripped = fenced[1].trim();
    }
    try {
        return JSON.parse(stripped);
    }
    catch {
        const start = stripped.indexOf('{');
        const end = stripped.lastIndexOf('}');
        if (start === -1 || end === -1 || end <= start) {
            throw new Error('Design intake did not return valid JSON.');
        }
        return JSON.parse(stripped.slice(start, end + 1));
    }
}
function normalizeDesignIntakeResult(value) {
    if (!isRecord(value)) {
        throw new Error('Design intake returned a non-object JSON value.');
    }
    const action = value.action === 'proceed' ? 'proceed' : 'ask';
    const readiness = parseReadiness(value.readiness);
    const normalizedSpec = isRecord(value.normalizedSpec) ? value.normalizedSpec : {};
    return {
        action,
        readiness,
        partFamily: typeof value.partFamily === 'string' ? value.partFamily : 'unknown',
        missingRequired: toStringArray(value.missingRequired),
        questions: toQuestions(value.questions),
        userMessage: typeof value.userMessage === 'string' ? value.userMessage : null,
        normalizedSpec,
    };
}
function parseReadiness(value) {
    if (value === 'ready' || value === 'assumptions_allowed' || value === 'blocked') {
        return value;
    }
    return 'blocked';
}
function toQuestions(value) {
    if (!Array.isArray(value)) {
        return [];
    }
    return value
        .filter(isRecord)
        .map((question) => ({
        id: typeof question.id === 'string' ? question.id : 'unknown',
        text: typeof question.text === 'string' ? question.text : 'Please provide more detail.',
        expects: parseExpectedAnswer(question.expects),
        required: typeof question.required === 'boolean' ? question.required : undefined,
        choices: toStringArray(question.choices),
        examples: toStringArray(question.examples),
        units: typeof question.units === 'string' ? question.units : undefined,
    }))
        .slice(0, 3);
}
function parseExpectedAnswer(value) {
    if (value === 'string'
        || value === 'number'
        || value === 'integer'
        || value === 'boolean'
        || value === 'choice'
        || value === 'multi_choice'
        || value === 'length'
        || value === 'dimensions'
        || value === 'angle') {
        return value;
    }
    return 'string';
}
function toStringArray(value) {
    return Array.isArray(value) ? value.filter((item) => typeof item === 'string') : [];
}
function isRecord(value) {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}
//# sourceMappingURL=lmstudio.js.map