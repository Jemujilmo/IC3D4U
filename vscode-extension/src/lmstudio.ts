import * as vscode from 'vscode';

export interface Message {
    role: 'system' | 'user' | 'assistant';
    content: string;
}

export type DesignReadiness = 'blocked' | 'assumptions_allowed' | 'ready';
export type DesignAction = 'ask' | 'proceed';
export type ExpectedAnswer =
    | 'string'
    | 'number'
    | 'integer'
    | 'boolean'
    | 'choice'
    | 'multi_choice'
    | 'length'
    | 'dimensions'
    | 'angle';

export interface ClarifyingQuestion {
    id: string;
    text: string;
    expects: ExpectedAnswer;
    required?: boolean;
    choices?: string[];
    examples?: string[];
    units?: string;
}

export interface NormalizedSpec {
    schemaVersion?: number;
    [key: string]: unknown;
}

export interface DesignIntakeResult {
    action: DesignAction;
    readiness: DesignReadiness;
    partFamily: string;
    missingRequired: string[];
    questions: ClarifyingQuestion[];
    userMessage: string | null;
    normalizedSpec: NormalizedSpec;
}

function extractCode(text: string): string {
    const match = text.match(/```(?:python)?\s*\n([\s\S]*?)```/);
    return match ? match[1].trim() : text.trim();
}

function getConfig() {
    const cfg = vscode.workspace.getConfiguration('ic3d4u');
    return {
        baseUrl: cfg.get<string>('lmStudioUrl', 'http://localhost:1234/v1'),
        model:   cfg.get<string>('modelName',   'qwen3-coder-30b-a3b-instruct'),
        maxTokens: cfg.get<number>('maxTokens', 3000),
    };
}

async function postChatCompletion(
    messages: Message[],
    token: vscode.CancellationToken
): Promise<string> {
    const { baseUrl, model, maxTokens } = getConfig();

    const controller = new AbortController();
    token.onCancellationRequested(() => controller.abort());

    let response: Response;
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
    } catch (err: any) {
        if (err.name === 'AbortError') {
            throw new Error('Cancelled');
        }
        throw new Error(
            `Cannot reach LM Studio at ${baseUrl}. Make sure the server is started.`
        );
    }

    if (!response.ok) {
        throw new Error(`LM Studio responded with HTTP ${response.status}`);
    }

    const data = (await response.json()) as {
        choices: { message: { content: string } }[];
    };

    return data.choices[0].message.content;
}

export async function callLMStudio(
    prompt: string,
    history: Message[],
    systemPrompt: string,
    token: vscode.CancellationToken
): Promise<{ code: string; raw: string }> {
    const messages: Message[] = [
        { role: 'system', content: systemPrompt },
        ...history,
        { role: 'user', content: prompt },
    ];

    const raw = await postChatCompletion(messages, token);
    const code = extractCode(raw);
    return { code, raw };
}

export async function callDesignIntake(
    prompt: string,
    history: Message[],
    systemPrompt: string,
    token: vscode.CancellationToken
): Promise<{ plan: DesignIntakeResult; raw: string }> {
    const messages: Message[] = [
        { role: 'system', content: systemPrompt },
        ...history,
        { role: 'user', content: prompt },
    ];

    const raw = await postChatCompletion(messages, token);
    const parsed = extractJson(raw);
    return { plan: normalizeDesignIntakeResult(parsed), raw };
}

export function canGenerateFromPlan(plan: DesignIntakeResult): boolean {
    return (
        plan.action === 'proceed'
        && (plan.readiness === 'ready' || plan.readiness === 'assumptions_allowed')
        && typeof plan.normalizedSpec === 'object'
        && plan.normalizedSpec !== null
    );
}

export function buildCodegenPrompt(plan: DesignIntakeResult): string {
    return (
        'Generate a complete FreeCAD Python script from this normalized design spec. ' +
        'Use the JSON as the source of truth and follow the system output rules.\n\n' +
        `NORMALIZED_SPEC_JSON:\n${JSON.stringify(plan.normalizedSpec, null, 2)}`
    );
}

export function designPlanHistoryMessage(plan: DesignIntakeResult): Message {
    return {
        role: 'assistant',
        content: 'Previous design intake result JSON:\n' + JSON.stringify(plan, null, 2),
    };
}

export function buildHistory(
    history: readonly (vscode.ChatRequestTurn | vscode.ChatResponseTurn)[]
): Message[] {
    const messages: Message[] = [];

    for (const turn of history) {
        if (turn instanceof vscode.ChatRequestTurn) {
            messages.push({ role: 'user', content: turn.prompt });
        } else if (turn instanceof vscode.ChatResponseTurn) {
            const text = turn.response
                .filter((p): p is vscode.ChatResponseMarkdownPart =>
                    p instanceof vscode.ChatResponseMarkdownPart
                )
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

function extractJson(text: string): unknown {
    let stripped = text.trim();
    const fenced = stripped.match(/```(?:json)?\s*\n([\s\S]*?)```/);
    if (fenced) {
        stripped = fenced[1].trim();
    }

    try {
        return JSON.parse(stripped);
    } catch {
        const start = stripped.indexOf('{');
        const end = stripped.lastIndexOf('}');
        if (start === -1 || end === -1 || end <= start) {
            throw new Error('Design intake did not return valid JSON.');
        }
        return JSON.parse(stripped.slice(start, end + 1));
    }
}

function normalizeDesignIntakeResult(value: unknown): DesignIntakeResult {
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

function parseReadiness(value: unknown): DesignReadiness {
    if (value === 'ready' || value === 'assumptions_allowed' || value === 'blocked') {
        return value;
    }
    return 'blocked';
}

function toQuestions(value: unknown): ClarifyingQuestion[] {
    if (!Array.isArray(value)) {
        return [];
    }

    return value
        .filter(isRecord)
        .map((question): ClarifyingQuestion => ({
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

function parseExpectedAnswer(value: unknown): ExpectedAnswer {
    if (
        value === 'string'
        || value === 'number'
        || value === 'integer'
        || value === 'boolean'
        || value === 'choice'
        || value === 'multi_choice'
        || value === 'length'
        || value === 'dimensions'
        || value === 'angle'
    ) {
        return value;
    }
    return 'string';
}

function toStringArray(value: unknown): string[] {
    return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}
