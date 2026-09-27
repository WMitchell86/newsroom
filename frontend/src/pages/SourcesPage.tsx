import { useId, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { createSource, updateSource } from "../api/client";
import { queryKeys, sourcesOptions } from "../api/queries";
import type { SourceKind, SourcePriority, SourceRow } from "../api/dto";
import { ErrorState, LoadingState, PageHeader } from "../shared/EditorPrimitives";
import { getErrorMessage } from "../shared/errorMessage";
import styles from "./SourcesPage.module.css";

/**
 * V1.2-G4: `Настройки → Източники`.
 *
 * The editor's direct control over the newsroom's source registry, with no JSON
 * and no backend vocabulary. Everything rendered here comes from
 * `/api/v1/settings/sources`, which is a projection of the one canonical
 * registry the collector already reads — this screen owns no source state of its
 * own beyond what is on screen (§2).
 *
 * What the editor can do, and nothing more (§STOP):
 *   - read what is monitored, what is trusted for facts, and what matters most;
 *   - turn a source on and off;
 *   - mark an appropriate publisher as `Надежден за факти`, with one
 *     confirmation when turning it ON (§21);
 *   - change a priority;
 *   - add a source.
 */

/** §6. Exactly the §6 sentence, shown next to the toggle that carries it. */
const AUTHORITY_HELP =
  "Когато източникът публикува информация от собствената си компетентност, тя може да се използва като първична фактическа основа.";

/** §21. One lightweight confirmation, and only when granting the authority. */
const AUTHORITY_CONFIRMATION =
  "Този източник ще може да служи като първична фактическа основа за информация от собствената му компетентност.";

/** §12. The canonical kinds, in the order an editor reasons about them. */
const KIND_OPTIONS: ReadonlyArray<{ value: SourceKind; label: string }> = [
  { value: "official", label: "Официален" },
  { value: "media", label: "Медия" },
  { value: "national", label: "Национална медия" },
  { value: "regional", label: "Регионална медия" },
  { value: "aggregator", label: "Агрегатор" },
];

/** §13. Three words. No numeric score is ever offered. */
const PRIORITY_OPTIONS: ReadonlyArray<{ value: SourcePriority; label: string }> = [
  { value: "high", label: "Висок" },
  { value: "normal", label: "Нормален" },
  { value: "low", label: "Нисък" },
];

/** §14. Trivial, derived from the DTO the list already carries. */
const FILTERS = [
  { id: "all", label: "Всички" },
  { id: "monitored", label: "Следени" },
  { id: "official", label: "Официални" },
  { id: "media", label: "Медии" },
] as const;

type FilterId = (typeof FILTERS)[number]["id"];

function matchesFilter(row: SourceRow, filter: FilterId): boolean {
  if (filter === "all") return true;
  if (filter === "monitored") return row.monitored;
  // §12: `Медии` covers the two media kinds, since an editor filtering for "media"
  // means "not an official body", not one exact stored value.
  if (filter === "media") return row.kind === "media" || row.kind === "national" || row.kind === "regional";
  return row.kind === filter;
}

/**
 * A switch that reads as a switch, not a checkbox.
 *
 * One pill carries both the state and its word: a separate track plus a separate
 * "Да"/"Не" label read as two small boxes in a dense table, and the editor has to
 * work out which part is the control. The word inside the pill makes the state
 * scannable down the column and the row readable without interpreting a shape.
 *
 * `role="switch"` plus `aria-checked` is what makes the state announceable; the
 * accessible name is the column plus the source, so a screen reader says which
 * source the control belongs to.
 */
function Toggle({
  checked,
  onLabel,
  offLabel,
  label,
  disabled,
  onChange,
}: {
  checked: boolean;
  onLabel: string;
  offLabel: string;
  label: string;
  disabled?: boolean;
  onChange: () => void;
}) {
  return <button
    type="button"
    role="switch"
    aria-checked={checked}
    aria-label={label}
    disabled={disabled}
    className={`${styles.switch} ${checked ? styles.switchOn : ""}`}
    onClick={onChange}
  >
    {checked ? onLabel : offLabel}
  </button>;
}

/**
 * `+ Добави източник` (§9).
 *
 * Six fields, and only six. `source_id`, the collector, the cadence and the
 * timestamps are derived server-side, so the form never asks the editor for a
 * field the registry merely happens to store — and can never be talked into
 * writing a wrong one.
 */
function AddSourceForm({ onDone }: { onDone: () => void }) {
  const queryClient = useQueryClient();
  const nameId = useId();
  const addressId = useId();
  const kindId = useId();
  const priorityId = useId();
  const [name, setName] = useState("");
  const [address, setAddress] = useState("");
  const [kind, setKind] = useState<SourceKind>("official");
  const [priority, setPriority] = useState<SourcePriority>("normal");
  const [monitored, setMonitored] = useState(true);
  const [factualAuthority, setFactualAuthority] = useState(false);

  const mutation = useMutation({
    mutationFn: () => createSource({ name, address, kind, monitored, factualAuthority, priority }),
    onSuccess: async () => {
      // §31: the row is refetched from the canonical registry, not patched in.
      await queryClient.invalidateQueries({ queryKey: queryKeys.sources });
      onDone();
    },
  });

  return <div className={styles.sheet}>
    <h2 className={styles.sheetTitle}>Нов източник</h2>
    <p className={styles.sheetNote}>
      Посочете къде да се публикува. Останалите настройки се попълват автоматично.
    </p>
    <div className={styles.fieldGrid}>
      <div className={styles.field}>
        <label className={styles.fieldLabel} htmlFor={nameId}>Име</label>
        <input
          id={nameId}
          className={styles.fieldInput}
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="Община Бургас"
        />
      </div>
      <div className={styles.field}>
        <label className={styles.fieldLabel} htmlFor={addressId}>URL / домейн</label>
        <input
          id={addressId}
          className={styles.fieldInput}
          value={address}
          onChange={(event) => setAddress(event.target.value)}
          placeholder="burgas.bg"
        />
      </div>
      <div className={styles.field}>
        <label className={styles.fieldLabel} htmlFor={kindId}>Тип</label>
        <select
          id={kindId}
          className={styles.fieldSelect}
          value={kind}
          onChange={(event) => setKind(event.target.value as SourceKind)}
        >
          {KIND_OPTIONS.map((option) =>
            <option key={option.value} value={option.value}>{option.label}</option>)}
        </select>
      </div>
      <div className={styles.field}>
        <label className={styles.fieldLabel} htmlFor={priorityId}>Приоритет</label>
        <select
          id={priorityId}
          className={styles.fieldSelect}
          value={priority}
          onChange={(event) => setPriority(event.target.value as SourcePriority)}
        >
          {PRIORITY_OPTIONS.map((option) =>
            <option key={option.value} value={option.value}>{option.label}</option>)}
        </select>
      </div>
      <div className={`${styles.field} ${styles.fieldWide}`}>
        <span className={styles.fieldLabel}>Следи се</span>
        <Toggle
          checked={monitored}
          onLabel="Да"
          offLabel="Не"
          label="Следи се"
          onChange={() => setMonitored((value) => !value)}
        />
      </div>
      <div className={`${styles.field} ${styles.fieldWide}`}>
        <span className={styles.fieldLabel}>Надежден за факти</span>
        <Toggle
          checked={factualAuthority}
          onLabel="Да"
          offLabel="Не"
          label="Надежден за факти"
          onChange={() => setFactualAuthority((value) => !value)}
        />
        <p className={styles.fieldHint}>{AUTHORITY_HELP}</p>
      </div>
    </div>
    {mutation.isError ? <p className={styles.sheetError} role="alert">{getErrorMessage(mutation.error)}</p> : null}
    <div className={styles.sheetActions}>
      <button
        type="button"
        className={styles.primaryAction}
        disabled={mutation.isPending}
        onClick={() => mutation.mutate()}
      >
        {mutation.isPending ? "Записва се…" : "Добави източник"}
      </button>
      <button type="button" className={styles.secondaryAction} onClick={onDone}>Отказ</button>
    </div>
  </div>;
}

/**
 * The inline editor for one row (§10).
 *
 * Four fields and nothing else: name, `Следи се`, `Надежден за факти`, and the
 * priority. The source's identity, its publisher domain and its collector are
 * not editable here, because the registry's own `EDITABLE_FIELDS` does not allow
 * it — the form cannot offer a control the backend would refuse.
 */
function SourceEditor({ source, onClose }: { source: SourceRow; onClose: () => void }) {
  const queryClient = useQueryClient();
  const nameId = useId();
  const priorityId = useId();
  const [name, setName] = useState(source.name);
  const [priority, setPriority] = useState<SourcePriority>(source.priority);
  const [monitored, setMonitored] = useState(source.monitored);
  const [factualAuthority, setFactualAuthority] = useState(source.factualAuthority);

  const mutation = useMutation({
    mutationFn: () => updateSource(source.id, { name, priority, monitored, factualAuthority }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.sources });
      onClose();
    },
  });

  return <div className={styles.sheet}>
    <h2 className={styles.sheetTitle}>{source.name}</h2>
    <p className={styles.sheetNote}>
      {source.address}
      {source.domain ? ` · ${source.domain}` : ""}
    </p>
    <div className={styles.fieldGrid}>
      <div className={styles.field}>
        <label className={styles.fieldLabel} htmlFor={nameId}>Име</label>
        <input
          id={nameId}
          className={styles.fieldInput}
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
      </div>
      <div className={styles.field}>
        <label className={styles.fieldLabel} htmlFor={priorityId}>Приоритет</label>
        <select
          id={priorityId}
          className={styles.fieldSelect}
          value={priority}
          onChange={(event) => setPriority(event.target.value as SourcePriority)}
        >
          {PRIORITY_OPTIONS.map((option) =>
            <option key={option.value} value={option.value}>{option.label}</option>)}
        </select>
      </div>
      <div className={`${styles.field} ${styles.fieldWide}`}>
        <span className={styles.fieldLabel}>Следи се</span>
        <Toggle
          checked={monitored}
          onLabel="Да"
          offLabel="Не"
          label="Следи се"
          onChange={() => setMonitored((value) => !value)}
        />
      </div>
      <div className={`${styles.field} ${styles.fieldWide}`}>
        <span className={styles.fieldLabel}>Надежден за факти</span>
        <Toggle
          checked={factualAuthority}
          onLabel="Да"
          offLabel="Не"
          label="Надежден за факти"
          onChange={() => setFactualAuthority((value) => !value)}
        />
        <p className={styles.fieldHint}>{AUTHORITY_HELP}</p>
      </div>
    </div>
    {mutation.isError ? <p className={styles.sheetError} role="alert">{getErrorMessage(mutation.error)}</p> : null}
    <div className={styles.sheetActions}>
      <button
        type="button"
        className={styles.primaryAction}
        disabled={mutation.isPending}
        onClick={() => mutation.mutate()}
      >
        {mutation.isPending ? "Записва се…" : "Запиши"}
      </button>
      <button type="button" className={styles.secondaryAction} onClick={onClose}>Отказ</button>
    </div>
  </div>;
}

/**
 * §21: the one confirmation in this slice.
 *
 * Turning factual authority ON grants the newsroom's first-party standing, so it
 * is worth one sentence of confirmation. Turning it OFF only removes a
 * permission, so it is applied immediately — a dialog to *lose* a restriction
 * would train the editor to click through dialogs.
 */
function AuthorityConfirmation({ source, onConfirm, onCancel }: {
  source: SourceRow;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const titleId = useId();
  return <div
    className={styles.sheet}
    role="alertdialog"
    aria-modal="true"
    aria-labelledby={titleId}
  >
    <h2 className={styles.sheetTitle} id={titleId}>Надежден за факти</h2>
    <p className={styles.sheetNote}>{AUTHORITY_CONFIRMATION}</p>
    <p className={styles.sheetNote}>{source.name}</p>
    <div className={styles.sheetActions}>
      <button type="button" className={styles.primaryAction} onClick={onConfirm}>Потвърди</button>
      <button type="button" className={styles.secondaryAction} onClick={onCancel}>Отказ</button>
    </div>
  </div>;
}

export function SourcesPage() {
  const queryClient = useQueryClient();
  const { data, isPending, isError, error, refetch } = useQuery(sourcesOptions());
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<FilterId>("all");
  const [adding, setAdding] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [pendingAuthority, setPendingAuthority] = useState<SourceRow | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [rowError, setRowError] = useState<string | null>(null);

  /**
   * One mutation path for both toggles and the priority, so a row can only ever
   * be changed by a request the backend validated (§10, §32).
   */
  const change = useMutation({
    mutationFn: ({ id, changes }: { id: string; changes: Parameters<typeof updateSource>[1] }) =>
      updateSource(id, changes),
    onMutate: ({ id }) => {
      setBusyId(id);
      setRowError(null);
    },
    onSuccess: async () => {
      // The server is the source of truth: the list is refetched, never patched
      // from an optimistic guess (§30, §31).
      await queryClient.invalidateQueries({ queryKey: queryKeys.sources });
    },
    onError: (failure) => {
      setRowError(getErrorMessage(failure));
    },
    onSettled: () => {
      setBusyId(null);
    },
  });

  const rows = useMemo(() => {
    const needle = search.trim().toLocaleLowerCase("bg-BG");
    return (data?.sources ?? []).filter((row) => {
      if (!matchesFilter(row, filter)) return false;
      if (!needle) return true;
      // §14: a compact search over what the editor can see on the row itself.
      return [row.name, row.domain, row.address, row.kindLabel]
        .some((value) => value.toLocaleLowerCase("bg-BG").includes(needle));
    });
  }, [data, search, filter]);

  const editing = data?.sources.find((row) => row.id === editingId) ?? null;

  function requestAuthority(row: SourceRow, next: boolean) {
    // §21: only the grant is confirmed. Losing the authority is immediate.
    if (next) {
      setPendingAuthority(row);
      return;
    }
    change.mutate({ id: row.id, changes: { factualAuthority: false } });
  }

  return <div className={styles.page}>
    <Link className={styles.backLink} to="/settings">← Настройки</Link>
    <PageHeader
      kicker="Настройки"
      title="Източници"
      lede="Източниците определят какво следим и кои първични публикации могат да се използват като фактическа основа."
    />

    <div className={styles.toolbar}>
      <div className={styles.searchField}>
        <label className={styles.searchLabel} htmlFor="sources-search">Търси източник</label>
        <input
          id="sources-search"
          className={styles.searchInput}
          type="search"
          value={search}
          placeholder="Търси източник…"
          onChange={(event) => setSearch(event.target.value)}
        />
      </div>
      <div className={styles.toolbarRight}>
        <div className={styles.filters} role="group" aria-label="Филтри">
          {FILTERS.map((option) => <button
            key={option.id}
            type="button"
            aria-pressed={filter === option.id}
            className={`${styles.filter} ${filter === option.id ? styles.filterActive : ""}`}
            onClick={() => setFilter(option.id)}
          >
            {option.label}
          </button>)}
        </div>
        <button type="button" className={styles.addButton} onClick={() => setAdding(true)}>
          + Добави източник
        </button>
      </div>
    </div>

    {data ? <p className={styles.counts}>
      <span>{data.summary.total} източника</span>
      <span>{data.summary.monitored} следени</span>
      <span>{data.summary.notMonitored} изключени</span>
      <span>{data.summary.factualAuthority} надеждни за факти</span>
      {data.summary.problems > 0 ? <span>{data.summary.problems} с проблем</span> : null}
    </p> : null}

    {/* §6: the meaning of `Надежден за факти` sits with the column it governs,
        not in a manual. It is the one column whose consequence an editor could
        otherwise misread, so it is stated once, above the list. */}
    <p className={styles.authorityHelp}>{AUTHORITY_HELP}</p>

    {adding ? <AddSourceForm onDone={() => setAdding(false)} /> : null}
    {editing && !adding ? <SourceEditor source={editing} onClose={() => setEditingId(null)} /> : null}
    {pendingAuthority ? <AuthorityConfirmation
      source={pendingAuthority}
      onCancel={() => setPendingAuthority(null)}
      onConfirm={() => {
        change.mutate({ id: pendingAuthority.id, changes: { factualAuthority: true } });
        setPendingAuthority(null);
      }}
    /> : null}

    {rowError ? <p className={styles.sheetError} role="alert">{rowError}</p> : null}

    {isPending ? <LoadingState label="Зареждат се източниците…" /> : null}
    {isError ? <ErrorState title="Източниците не можа да се заредят" error={error} onRetry={() => refetch()} /> : null}

    {data ? <table className={styles.table}>
      <thead>
        <tr>
          <th scope="col" className={styles.nameColumn}>Източник</th>
          <th scope="col" className={styles.kindColumn}>Тип</th>
          <th scope="col" className={styles.addressColumn}>Адрес / домейн</th>
          <th scope="col" className={styles.watchColumn}>Следи се</th>
          <th scope="col" className={styles.authorityColumn}>Надежден за факти</th>
          <th scope="col" className={styles.priorityColumn}>Приоритет</th>
          <th scope="col" className={styles.actionColumn}><span className={styles.srOnly}>Действия</span></th>
        </tr>
      </thead>
      <tbody>
        {rows.length === 0 ? <tr>
          <td className={styles.emptyRow} colSpan={7}>Няма източници по този филтър.</td>
        </tr> : rows.map((row) => <tr key={row.id}>
          <td className={styles.nameCell}>
            <span className={`${styles.sourceName} ${row.monitored ? "" : styles.notMonitoredName}`}>
              {row.name}
            </span>
            {row.health.status === "problem" ? <span className={styles.problemFlag}>Проблем</span> : null}
          </td>
          <td className={`${styles.mutedCell} ${styles.kindColumn}`}>{row.kindLabel}</td>
          <td className={`${styles.mutedCell} ${styles.addressColumn}`} title={row.address}>
            {row.domain || row.address}
          </td>
          <td className={styles.watchColumn}>
            <Toggle
              checked={row.monitored}
              onLabel="Да"
              offLabel="Не"
              label={`Следи се: ${row.name}`}
              disabled={busyId === row.id}
              onChange={() => change.mutate({ id: row.id, changes: { monitored: !row.monitored } })}
            />
          </td>
          <td className={styles.authorityColumn}>
            <Toggle
              checked={row.factualAuthority}
              onLabel="Да"
              offLabel="Не"
              label={`Надежден за факти: ${row.name}`}
              disabled={busyId === row.id}
              onChange={() => requestAuthority(row, !row.factualAuthority)}
            />
          </td>
          <td className={styles.mutedCell + " " + styles.priorityColumn}>{row.priorityLabel}</td>
          <td className={styles.actionColumn}>
            <button
              type="button"
              className={styles.editButton}
              onClick={() => setEditingId(row.id)}
            >
              Редактирай
            </button>
          </td>
        </tr>)}
      </tbody>
    </table> : null}
  </div>;
}

