"use client";

import { ArrowUpRight, Wrench } from "lucide-react";
import Link from "next/link";
import { useState, type ReactNode } from "react";

import {
  FieldShell,
  NumberField,
  RowList,
  Section,
  SelectField,
  SwitchField,
  TemplateField,
  TextField,
  issueAt,
  mono,
} from "@/components/editor/fields";
import { NodeIcon } from "@/components/node-icon";
import { Input, NativeSelect, Textarea } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/cn";
import { FIELD_TYPES, OPERATORS, displayLabel } from "@/lib/nodes";
import { useKnowledgeBases, useModels } from "@/lib/queries";
import type { GraphDocument, GraphNode, Issue } from "@/lib/types";
import type { Variable } from "@/lib/variables";

export type FormProps = {
  node: GraphNode;
  set: (patch: Record<string, unknown>) => void;
  issues: Issue[];
  variables: Variable[];
  readOnly: boolean;
  workspace: string;
  graph: GraphDocument;
  onSelectNode: (id: string) => void;
};

type Row = Record<string, unknown>;

const text = (value: unknown): string => (typeof value === "string" ? value : "");
const rows = <T extends Row>(value: unknown): T[] => (Array.isArray(value) ? (value as T[]) : []);
const strings = (value: unknown): string[] => (Array.isArray(value) ? value.map(String) : []);
const identifier = (value: string) => value.replace(/[^A-Za-z0-9_]/g, "_").slice(0, 64);

// ---------------------------------------------------------------------------------------
// Start and Output
// ---------------------------------------------------------------------------------------

function JsonText({
  label,
  value,
  onChange,
  hint,
  disabled,
}: {
  label: string;
  value: unknown;
  onChange: (value: unknown) => void;
  hint?: ReactNode;
  disabled?: boolean;
}) {
  // The inspector remounts per node, so the text only needs its initial value here.
  const [draft, setDraft] = useState(() => JSON.stringify(value ?? {}, null, 2));
  const [error, setError] = useState<string | null>(null);
  return (
    <FieldShell label={label} hint={hint} error={error ? `JSON: ${error}` : undefined}>
      <Textarea
        rows={6}
        aria-label={label}
        className={cn(mono, error && "border-danger")}
        value={draft}
        disabled={disabled}
        spellCheck={false}
        onChange={(event) => {
          setDraft(event.target.value);
          try {
            onChange(event.target.value.trim() ? JSON.parse(event.target.value) : {});
            setError(null);
          } catch (exc) {
            setError(exc instanceof Error ? exc.message : "not valid");
          }
        }}
      />
    </FieldShell>
  );
}

function StartForm({ node, set, issues, readOnly }: FormProps) {
  const inputs = rows<Row>(node.config.inputs);
  return (
    <>
      <Section title="Inputs">
        <FieldShell
          label="Run inputs"
          hint="Each input is available to every step as {{inputs.name}}."
          error={issueAt(issues, "inputs")}
        >
          <RowList
            rows={inputs}
            disabled={readOnly}
            max={30}
            addLabel="Add input"
            empty="This flow takes no inputs."
            make={() => ({ name: "", type: "string", description: "", required: true })}
            onChange={(next) => set({ inputs: next })}
            render={(row, update) => (
              <div className="border-border space-y-2 rounded-lg border p-2">
                <div className="grid grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)] gap-2">
                  <Input
                    aria-label="Input name"
                    placeholder="name"
                    className={mono}
                    value={text(row.name)}
                    disabled={readOnly}
                    onChange={(e) => update({ name: identifier(e.target.value) })}
                  />
                  <NativeSelect
                    aria-label="Input type"
                    value={text(row.type) || "string"}
                    disabled={readOnly}
                    onChange={(e) => update({ type: e.target.value })}
                  >
                    {FIELD_TYPES.map((type) => (
                      <option key={type} value={type}>
                        {type}
                      </option>
                    ))}
                  </NativeSelect>
                </div>
                <Input
                  aria-label="Input description"
                  placeholder="What it is (shown to whoever starts a run)"
                  value={text(row.description)}
                  disabled={readOnly}
                  onChange={(e) => update({ description: e.target.value })}
                />
                <label className="text-muted-foreground flex items-center justify-between text-[12.5px]">
                  Required
                  <Switch
                    checked={row.required !== false}
                    disabled={readOnly}
                    onCheckedChange={(required) => update({ required })}
                    aria-label="Required"
                  />
                </label>
              </div>
            )}
          />
        </FieldShell>
      </Section>
      <Section title="Sample">
        <JsonText
          label="Sample inputs"
          value={node.config.sample}
          disabled={readOnly}
          hint="Prefills the Run dialog, so a test run is one click."
          onChange={(sample) => set({ sample })}
        />
      </Section>
    </>
  );
}

function OutputForm({ node, set, issues, variables, readOnly }: FormProps) {
  return (
    <Section title="Result">
      <FieldShell
        label="Output fields"
        hint="The run's result. Each value is a template, usually a reference to an earlier step."
        error={issueAt(issues, "fields")}
      >
        <RowList
          rows={rows<Row>(node.config.fields)}
          disabled={readOnly}
          max={30}
          addLabel="Add field"
          make={() => ({ name: "", value: "" })}
          onChange={(fields) => set({ fields })}
          render={(row, update, index) => (
            <div className="border-border space-y-2 rounded-lg border p-2">
              <Input
                aria-label="Field name"
                placeholder="name"
                className={mono}
                value={text(row.name)}
                disabled={readOnly}
                onChange={(e) => update({ name: identifier(e.target.value) })}
              />
              <TemplateField
                label="Value"
                value={text(row.value)}
                variables={variables}
                disabled={readOnly}
                placeholder="{{prompt.text}}"
                error={issueAt(issues, `fields.${index}.value`)}
                onChange={(value) => update({ value })}
              />
            </div>
          )}
        />
      </FieldShell>
    </Section>
  );
}

// ---------------------------------------------------------------------------------------
// Model nodes: Prompt and Agent
// ---------------------------------------------------------------------------------------

function ModelSelect({
  value,
  onChange,
  issues,
  readOnly,
}: {
  value: string;
  onChange: (value: string) => void;
  issues: Issue[];
  readOnly: boolean;
}) {
  const models = useModels();
  const options = (models.data ?? []).map((m) => ({
    value: m.ref,
    label: m.offline ? m.label : `${m.label} (${m.provider})`,
  }));
  if (value && !options.some((o) => o.value === value)) {
    options.unshift({ value, label: `${value} (not configured here)` });
  }
  return (
    <SelectField
      label="Model"
      value={value}
      options={options.length ? options : [{ value, label: value }]}
      onChange={onChange}
      disabled={readOnly}
      error={issueAt(issues, "model")}
      hint="The offline model answers instantly with no API key and the same output every time."
    />
  );
}

function JsonFields({ node, set, issues, readOnly }: FormProps) {
  return (
    <FieldShell
      label="Fields to return"
      hint="The model answers with exactly these fields, read as {{id.json.field}}."
      error={issueAt(issues, "json_fields")}
    >
      <RowList
        rows={rows<Row>(node.config.json_fields)}
        disabled={readOnly}
        max={40}
        addLabel="Add field"
        make={() => ({ name: "", type: "string", description: "", enum: [] })}
        onChange={(json_fields) => set({ json_fields })}
        render={(row, update) => (
          <div className="border-border space-y-2 rounded-lg border p-2">
            <div className="grid grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)] gap-2">
              <Input
                aria-label="Field name"
                placeholder="category"
                className={mono}
                value={text(row.name)}
                disabled={readOnly}
                onChange={(e) => update({ name: identifier(e.target.value) })}
              />
              <NativeSelect
                aria-label="Field type"
                value={text(row.type) || "string"}
                disabled={readOnly}
                onChange={(e) => update({ type: e.target.value })}
              >
                {FIELD_TYPES.map((type) => (
                  <option key={type} value={type}>
                    {type}
                  </option>
                ))}
              </NativeSelect>
            </div>
            <Input
              aria-label="Field description"
              placeholder="What the field holds"
              value={text(row.description)}
              disabled={readOnly}
              onChange={(e) => update({ description: e.target.value })}
            />
            <Input
              aria-label="Allowed values"
              placeholder="Allowed values, comma separated (optional)"
              className={mono}
              value={strings(row.enum).join(", ")}
              disabled={readOnly}
              onChange={(e) =>
                update({
                  enum: e.target.value
                    .split(",")
                    .map((part) => part.trim())
                    .filter(Boolean),
                })
              }
            />
          </div>
        )}
      />
    </FieldShell>
  );
}

function ModelSettings(props: FormProps) {
  const { node, set, issues, readOnly } = props;
  const outputMode = text(node.config.output_mode) || "text";
  return (
    <Section title="Model">
      <ModelSelect
        value={text(node.config.model)}
        onChange={(model) => set({ model })}
        issues={issues}
        readOnly={readOnly}
      />
      <div className="grid grid-cols-2 gap-3">
        <NumberField
          label="Temperature"
          value={Number(node.config.temperature ?? 0.2)}
          min={0}
          max={2}
          step={0.1}
          disabled={readOnly}
          error={issueAt(issues, "temperature")}
          onChange={(temperature) => set({ temperature })}
        />
        <NumberField
          label="Max tokens"
          value={Number(node.config.max_tokens ?? 800)}
          min={1}
          max={32000}
          disabled={readOnly}
          error={issueAt(issues, "max_tokens")}
          onChange={(max_tokens) => set({ max_tokens })}
        />
      </div>
      <SelectField
        label="Output"
        value={outputMode}
        disabled={readOnly}
        options={[
          { value: "text", label: "Text" },
          { value: "json", label: "Structured JSON fields" },
        ]}
        onChange={(output_mode) => set({ output_mode })}
      />
      {outputMode === "json" ? <JsonFields {...props} /> : null}
    </Section>
  );
}

function LlmForm(props: FormProps) {
  const { node, set, issues, variables, readOnly } = props;
  return (
    <>
      <Section title="Prompt">
        <TemplateField
          label="System"
          multiline
          rows={3}
          monospace={false}
          value={text(node.config.system)}
          variables={variables}
          disabled={readOnly}
          placeholder="You are a support specialist. Be concise."
          error={issueAt(issues, "system")}
          onChange={(system) => set({ system })}
        />
        <TemplateField
          label="Prompt"
          multiline
          rows={7}
          monospace={false}
          value={text(node.config.prompt)}
          variables={variables}
          disabled={readOnly}
          placeholder="Classify this ticket: {{inputs.body}}"
          error={issueAt(issues, "prompt")}
          onChange={(prompt) => set({ prompt })}
        />
      </Section>
      <ModelSettings {...props} />
    </>
  );
}

function AgentTools({ node, graph, onSelectNode }: FormProps) {
  const tools = graph.edges
    .filter((e) => e.target === node.id && e.target_handle === "tools")
    .map((e) => graph.nodes.find((n) => n.id === e.source))
    .filter((n): n is GraphNode => Boolean(n));
  return (
    <FieldShell
      label="Tools"
      hint="Wire a tool's As a tool output into this agent's Tools input to lend it."
    >
      {tools.length ? (
        <ul className="space-y-1.5">
          {tools.map((tool) => (
            <li key={tool.id}>
              <button
                type="button"
                onClick={() => onSelectNode(tool.id)}
                className="border-border hover:bg-muted flex w-full items-center gap-2 rounded-lg border px-2 py-1.5 text-left"
              >
                <NodeIcon type={tool.type} className="size-6 [&_svg]:size-3.5" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] font-medium">
                    {displayLabel(tool)}
                  </span>
                  <code className="text-muted-foreground font-mono text-[11px]">
                    {text(tool.config.tool_name) || tool.id}
                  </code>
                </span>
                <ArrowUpRight className="text-subtle size-3.5" aria-hidden />
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="border-border text-muted-foreground flex items-center gap-2 rounded-lg border border-dashed px-3 py-2 text-xs">
          <Wrench className="size-3.5" aria-hidden /> No tools yet: the agent will answer from the
          task alone.
        </p>
      )}
    </FieldShell>
  );
}

function AgentForm(props: FormProps) {
  const { node, set, issues, variables, readOnly } = props;
  return (
    <>
      <Section title="Task">
        <TemplateField
          label="System"
          multiline
          rows={3}
          monospace={false}
          value={text(node.config.system)}
          variables={variables}
          disabled={readOnly}
          placeholder="You are a sales representative. Sign off as Jordan Lee."
          error={issueAt(issues, "system")}
          onChange={(system) => set({ system })}
        />
        <TemplateField
          label="Task"
          multiline
          rows={7}
          monospace={false}
          value={text(node.config.task)}
          variables={variables}
          disabled={readOnly}
          placeholder="Look up the customer, then draft a reply to {{inputs.subject}}."
          error={issueAt(issues, "task")}
          onChange={(task) => set({ task })}
        />
        <NumberField
          label="Most tool rounds"
          value={Number(node.config.max_iterations ?? 5)}
          min={1}
          max={50}
          disabled={readOnly}
          hint="The agent answers without tools once it runs out of rounds."
          error={issueAt(issues, "max_iterations")}
          onChange={(max_iterations) => set({ max_iterations })}
        />
        <AgentTools {...props} />
      </Section>
      <ModelSettings {...props} />
    </>
  );
}

// ---------------------------------------------------------------------------------------
// Tools
// ---------------------------------------------------------------------------------------

function ToolSettings({
  node,
  set,
  issues,
  readOnly,
  graph,
  children,
}: FormProps & {
  children?: ReactNode;
}) {
  const lent = graph.edges.some((e) => e.source === node.id && e.target_handle === "tools");
  return (
    <Section title={lent ? "As an agent tool" : "As an agent tool (not wired)"}>
      <TextField
        label="Tool name"
        value={text(node.config.tool_name)}
        monospace
        placeholder={node.id}
        disabled={readOnly}
        hint="How the agent calls it. Defaults to the node id."
        error={issueAt(issues, "tool_name")}
        onChange={(value) =>
          set({ tool_name: value ? value.replace(/[^A-Za-z0-9_-]/g, "_") : null })
        }
      />
      <FieldShell label="Description for the agent" error={issueAt(issues, "tool_description")}>
        <Textarea
          rows={2}
          aria-label="Description for the agent"
          value={text(node.config.tool_description)}
          disabled={readOnly}
          placeholder="Look up a customer by email in the CRM."
          onChange={(e) => set({ tool_description: e.target.value })}
        />
      </FieldShell>
      {children}
    </Section>
  );
}

function KeyValues({
  label,
  value,
  onChange,
  variables,
  issues,
  field,
  readOnly,
}: {
  label: string;
  value: unknown;
  onChange: (value: Row[]) => void;
  variables: Variable[];
  issues: Issue[];
  field: string;
  readOnly: boolean;
}) {
  return (
    <FieldShell label={label} error={issueAt(issues, field)}>
      <RowList
        rows={rows<Row>(value)}
        disabled={readOnly}
        max={30}
        addLabel={`Add ${label.toLowerCase().replace(/s$/, "")}`}
        empty="None."
        make={() => ({ key: "", value: "" })}
        onChange={onChange}
        render={(row, update, index) => (
          <div className="border-border space-y-2 rounded-lg border p-2">
            <Input
              aria-label={`${label} name`}
              placeholder="Name"
              className={mono}
              value={text(row.key)}
              disabled={readOnly}
              onChange={(e) => update({ key: e.target.value })}
            />
            <TemplateField
              label="Value"
              value={text(row.value)}
              variables={variables}
              disabled={readOnly}
              placeholder="Bearer {{secrets.CRM_TOKEN}}"
              error={issueAt(issues, `${field}.${index}.value`)}
              onChange={(next) => update({ value: next })}
            />
          </div>
        )}
      />
    </FieldShell>
  );
}

function HttpForm(props: FormProps) {
  const { node, set, issues, variables, readOnly } = props;
  const bodyMode = text(node.config.body_mode) || "none";
  return (
    <>
      <Section title="Request">
        <div className="grid grid-cols-[6.5rem_minmax(0,1fr)] items-start gap-2">
          <SelectField
            label="Method"
            value={text(node.config.method) || "GET"}
            disabled={readOnly}
            options={["GET", "POST", "PUT", "PATCH", "DELETE"].map((m) => ({ value: m, label: m }))}
            onChange={(method) => set({ method })}
          />
          <TemplateField
            label="URL"
            value={text(node.config.url)}
            variables={variables}
            disabled={readOnly}
            placeholder="https://sandbox.agentstudio.test/crm/contacts"
            error={issueAt(issues, "url")}
            onChange={(url) => set({ url })}
          />
        </div>
        <KeyValues
          label="Query parameters"
          field="query"
          value={node.config.query}
          variables={variables}
          issues={issues}
          readOnly={readOnly}
          onChange={(query) => set({ query })}
        />
        <KeyValues
          label="Headers"
          field="headers"
          value={node.config.headers}
          variables={variables}
          issues={issues}
          readOnly={readOnly}
          onChange={(headers) => set({ headers })}
        />
        <SelectField
          label="Body"
          value={bodyMode}
          disabled={readOnly}
          options={[
            { value: "none", label: "No body" },
            { value: "json", label: "JSON" },
            { value: "text", label: "Text" },
          ]}
          onChange={(body_mode) => set({ body_mode })}
        />
        {bodyMode !== "none" ? (
          <TemplateField
            label={bodyMode === "json" ? "JSON body" : "Text body"}
            multiline
            rows={5}
            value={text(node.config.body)}
            variables={variables}
            disabled={readOnly}
            placeholder={'{"email": "{{inputs.email}}"}'}
            error={issueAt(issues, "body")}
            onChange={(body) => set({ body })}
          />
        ) : null}
        <div className="grid grid-cols-2 gap-3">
          <SelectField
            label="Read the response as"
            value={text(node.config.expect) || "json"}
            disabled={readOnly}
            options={[
              { value: "json", label: "JSON" },
              { value: "text", label: "Text" },
            ]}
            onChange={(expect) => set({ expect })}
          />
          <div className="pt-6">
            <SwitchField
              label="Fail on 4xx and 5xx"
              checked={node.config.fail_on_status !== false}
              disabled={readOnly}
              onChange={(fail_on_status) => set({ fail_on_status })}
            />
          </div>
        </div>
      </Section>
      <ToolSettings {...props}>
        <FieldShell
          label="Parameters the agent fills in"
          hint="Use them anywhere above as {{args.name}}."
          error={issueAt(issues, "parameters")}
        >
          <RowList
            rows={rows<Row>(node.config.parameters)}
            disabled={readOnly}
            max={20}
            addLabel="Add parameter"
            empty="None: the agent calls the request as configured."
            make={() => ({ name: "", type: "string", description: "", required: true })}
            onChange={(parameters) => set({ parameters })}
            render={(row, update) => (
              <div className="border-border space-y-2 rounded-lg border p-2">
                <div className="grid grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)] gap-2">
                  <Input
                    aria-label="Parameter name"
                    placeholder="email"
                    className={mono}
                    value={text(row.name)}
                    disabled={readOnly}
                    onChange={(e) => update({ name: identifier(e.target.value) })}
                  />
                  <NativeSelect
                    aria-label="Parameter type"
                    value={text(row.type) || "string"}
                    disabled={readOnly}
                    onChange={(e) => update({ type: e.target.value })}
                  >
                    {["string", "number", "integer", "boolean"].map((type) => (
                      <option key={type} value={type}>
                        {type}
                      </option>
                    ))}
                  </NativeSelect>
                </div>
                <Input
                  aria-label="Parameter description"
                  placeholder="What the agent should pass"
                  value={text(row.description)}
                  disabled={readOnly}
                  onChange={(e) => update({ description: e.target.value })}
                />
              </div>
            )}
          />
        </FieldShell>
      </ToolSettings>
    </>
  );
}

function KnowledgeForm(props: FormProps) {
  const { node, set, issues, variables, readOnly, workspace } = props;
  const kbs = useKnowledgeBases(workspace);
  const items = kbs.data?.items ?? [];
  const current = text(node.config.knowledge_base_id);
  return (
    <>
      <Section title="Search">
        <FieldShell
          label="Knowledge base"
          error={issueAt(issues, "knowledge_base_id")}
          action={
            <Link
              href={`/w/${workspace}/knowledge`}
              className="text-primary text-[11.5px] font-medium hover:underline"
            >
              Manage
            </Link>
          }
        >
          <NativeSelect
            aria-label="Knowledge base"
            value={current}
            disabled={readOnly}
            onChange={(e) => set({ knowledge_base_id: e.target.value })}
          >
            <option value="">Choose a knowledge base</option>
            {items.map((kb) => (
              <option key={kb.id} value={kb.id}>
                {kb.name} ({kb.document_count} documents)
              </option>
            ))}
          </NativeSelect>
        </FieldShell>
        <TemplateField
          label="Query"
          value={text(node.config.query)}
          variables={variables}
          disabled={readOnly}
          placeholder="{{inputs.question}}"
          hint="Leave empty when lent to an agent: it writes its own query."
          error={issueAt(issues, "query")}
          onChange={(query) => set({ query })}
        />
        <NumberField
          label="Passages to return"
          value={Number(node.config.top_k ?? 4)}
          min={1}
          max={20}
          disabled={readOnly}
          error={issueAt(issues, "top_k")}
          onChange={(top_k) => set({ top_k })}
        />
      </Section>
      <ToolSettings {...props} />
    </>
  );
}

function CalculatorForm(props: FormProps) {
  const { node, set, issues, variables, readOnly } = props;
  return (
    <>
      <Section title="Calculation">
        <TemplateField
          label="Expression"
          value={text(node.config.expression)}
          variables={variables}
          disabled={readOnly}
          placeholder="round({{extract.json.total}} * 1.2, 2)"
          hint="Numbers, + - * / // % **, parentheses, and round, min, max, abs, sum."
          error={issueAt(issues, "expression")}
          onChange={(expression) => set({ expression })}
        />
      </Section>
      <ToolSettings {...props} />
    </>
  );
}

function TransformForm(props: FormProps) {
  const { node, set, issues, variables, readOnly } = props;
  return (
    <>
      <Section title="Transform">
        <TemplateField
          label="Data"
          value={text(node.config.input)}
          variables={variables}
          disabled={readOnly}
          placeholder="{{lookup.json}}"
          error={issueAt(issues, "input")}
          onChange={(input) => set({ input })}
        />
        <TextField
          label="JMESPath expression"
          monospace
          value={text(node.config.expression)}
          disabled={readOnly}
          placeholder="items[?qty > `0`].{sku: sku, total: price}"
          error={issueAt(issues, "expression")}
          onChange={(expression) => set({ expression })}
        />
      </Section>
      <ToolSettings {...props} />
    </>
  );
}

// ---------------------------------------------------------------------------------------
// Logic and people
// ---------------------------------------------------------------------------------------

function ConditionForm({ node, set, issues, variables, readOnly }: FormProps) {
  const routes = rows<Row>(node.config.routes);
  return (
    <Section title="Branches">
      <p className="text-muted-foreground text-xs">
        Branches are tested top to bottom; the first that matches is taken, otherwise Else.
      </p>
      <RowList
        rows={routes}
        disabled={readOnly}
        max={10}
        addLabel="Add branch"
        make={() => ({
          id: `route_${routes.length + 1}`.replace("route_", "branch_"),
          label: `Branch ${routes.length + 1}`,
          match: "all",
          rules: [{ left: "", operator: "equals", right: "" }],
        })}
        onChange={(next) => set({ routes: next })}
        render={(route, update, routeIndex) => (
          <div className="border-border space-y-2.5 rounded-lg border p-2.5">
            <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-2">
              <Input
                aria-label="Branch label"
                placeholder="Label"
                value={text(route.label)}
                disabled={readOnly}
                onChange={(e) => update({ label: e.target.value })}
              />
              <Input
                aria-label="Branch id"
                placeholder="id"
                className={mono}
                value={text(route.id)}
                disabled={readOnly}
                onChange={(e) =>
                  update({
                    id: e.target.value
                      .toLowerCase()
                      .replace(/[^a-z0-9_]/g, "_")
                      .slice(0, 24),
                  })
                }
              />
            </div>
            <NativeSelect
              aria-label="How rules combine"
              value={text(route.match) || "all"}
              disabled={readOnly}
              onChange={(e) => update({ match: e.target.value })}
            >
              <option value="all">When all rules match</option>
              <option value="any">When any rule matches</option>
            </NativeSelect>
            <RowList
              rows={rows<Row>(route.rules)}
              disabled={readOnly}
              max={10}
              addLabel="Add rule"
              make={() => ({ left: "", operator: "equals", right: "" })}
              onChange={(rules) => update({ rules })}
              render={(rule, updateRule, ruleIndex) => {
                const unary = OPERATORS.find((o) => o.value === rule.operator)?.unary;
                const base = `routes.${routeIndex}.rules.${ruleIndex}`;
                return (
                  <div className="bg-muted/50 space-y-2 rounded-md p-2">
                    <TemplateField
                      label="Value"
                      value={text(rule.left)}
                      variables={variables}
                      disabled={readOnly}
                      placeholder="{{classify.json.priority}}"
                      error={issueAt(issues, `${base}.left`)}
                      onChange={(left) => updateRule({ left })}
                    />
                    <NativeSelect
                      aria-label="Operator"
                      value={text(rule.operator) || "equals"}
                      disabled={readOnly}
                      onChange={(e) => updateRule({ operator: e.target.value })}
                    >
                      {OPERATORS.map((operator) => (
                        <option key={operator.value} value={operator.value}>
                          {operator.label}
                        </option>
                      ))}
                    </NativeSelect>
                    {unary ? null : (
                      <TemplateField
                        label="Compare with"
                        value={text(rule.right)}
                        variables={variables}
                        disabled={readOnly}
                        placeholder="urgent"
                        error={issueAt(issues, `${base}.right`)}
                        onChange={(right) => updateRule({ right })}
                      />
                    )}
                  </div>
                );
              }}
            />
          </div>
        )}
      />
      {issueAt(issues, "routes") ? (
        <p className="text-danger text-xs font-medium">{issueAt(issues, "routes")}</p>
      ) : null}
    </Section>
  );
}

function LoopForm({ node, set, issues, variables, readOnly }: FormProps) {
  return (
    <Section title="Loop">
      <TemplateField
        label="Items"
        value={text(node.config.items)}
        variables={variables}
        disabled={readOnly}
        placeholder="{{extract_actions.json.actions}}"
        hint="A list. Steps wired to Each item run once per item and read {{item}} and {{index}}."
        error={issueAt(issues, "items")}
        onChange={(items) => set({ items })}
      />
      <div className="grid grid-cols-2 gap-3">
        <NumberField
          label="Most items"
          value={Number(node.config.max_items ?? 50)}
          min={1}
          max={10000}
          disabled={readOnly}
          error={issueAt(issues, "max_items")}
          onChange={(max_items) => set({ max_items })}
        />
        <NumberField
          label="In parallel"
          value={Number(node.config.concurrency ?? 1)}
          min={1}
          max={8}
          disabled={readOnly}
          error={issueAt(issues, "concurrency")}
          onChange={(concurrency) => set({ concurrency })}
        />
      </div>
      <TemplateField
        label="Collect per item"
        value={text(node.config.collect)}
        variables={variables}
        disabled={readOnly}
        placeholder="{{create_task.json.id}}"
        hint="What goes into {{id.results}} for each item. Empty collects the last step's output."
        error={issueAt(issues, "collect")}
        onChange={(collect) => set({ collect })}
      />
      <SwitchField
        label="Keep going when an item fails"
        checked={Boolean(node.config.continue_on_item_error)}
        disabled={readOnly}
        onChange={(continue_on_item_error) => set({ continue_on_item_error })}
      />
    </Section>
  );
}

function ApprovalForm({ node, set, issues, variables, readOnly }: FormProps) {
  return (
    <Section title="Review">
      <TemplateField
        label="Title"
        value={text(node.config.title)}
        variables={variables}
        disabled={readOnly}
        placeholder="Review reply: {{inputs.subject}}"
        error={issueAt(issues, "title")}
        onChange={(title) => set({ title })}
      />
      <TemplateField
        label="What the reviewer sees"
        multiline
        rows={6}
        monospace={false}
        value={text(node.config.message)}
        variables={variables}
        disabled={readOnly}
        placeholder="{{draft_reply.text}}"
        error={issueAt(issues, "message")}
        onChange={(message) => set({ message })}
      />
      <NumberField
        label="Expire after (hours)"
        nullable
        value={(node.config.expires_after_hours as number | null) ?? null}
        min={0.1}
        max={2160}
        step="any"
        disabled={readOnly}
        hint="An expired request counts as rejected. Empty waits as long as it takes."
        error={issueAt(issues, "expires_after_hours")}
        onChange={(expires_after_hours) => set({ expires_after_hours })}
      />
    </Section>
  );
}

function NoteForm({ node, set, readOnly }: FormProps) {
  // Literal class names, so Tailwind sees every one of them.
  const swatch = {
    yellow: "bg-note-yellow",
    blue: "bg-note-blue",
    green: "bg-note-green",
    pink: "bg-note-pink",
    gray: "bg-note-gray",
  } as const;
  const colors = Object.keys(swatch) as (keyof typeof swatch)[];
  const current = text(node.config.color) || "yellow";
  return (
    <Section title="Note">
      <FieldShell label="Text">
        <Textarea
          rows={6}
          aria-label="Note text"
          value={text(node.config.text)}
          disabled={readOnly}
          onChange={(e) => set({ text: e.target.value })}
        />
      </FieldShell>
      <FieldShell label="Colour">
        <div className="flex gap-2">
          {colors.map((color) => (
            <button
              key={color}
              type="button"
              disabled={readOnly}
              aria-label={color}
              aria-pressed={current === color}
              onClick={() => set({ color })}
              className={cn(
                "size-7 rounded-full border-2 border-transparent",
                swatch[color],
                current === color && "border-primary",
              )}
            />
          ))}
        </div>
      </FieldShell>
    </Section>
  );
}

const FORMS: Record<string, (props: FormProps) => ReactNode> = {
  start: StartForm,
  llm: LlmForm,
  agent: AgentForm,
  http: HttpForm,
  knowledge: KnowledgeForm,
  calculator: CalculatorForm,
  json_transform: TransformForm,
  condition: ConditionForm,
  loop: LoopForm,
  approval: ApprovalForm,
  output: OutputForm,
  note: NoteForm,
};

export function NodeForm(props: FormProps) {
  const Form = FORMS[props.node.type];
  if (!Form) {
    return <p className="text-muted-foreground text-[13px]">This node type has no settings.</p>;
  }
  return <Form {...props} />;
}
