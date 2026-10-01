import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { getModelSettings, setPaidModels } from "../api/client";
import { queryKeys } from "../api/queries";
import { ErrorState, LoadingState, PageHeader, Section } from "../shared/EditorPrimitives";
import { getErrorMessage } from "../shared/errorMessage";
import styles from "./ModelsSettingsPage.module.css";

/**
 * V1.2-G4.39 — `Настройки → AI и модели`: the paid-model switch.
 *
 * This capability already existed and worked, on the server-rendered `/models`
 * page. BACKLOG recorded `AI и модели` under Settings as "still unimplemented"
 * and deliberately kept it out of the Settings screen rather than ship it as an
 * empty tab — which was right: the name promised a screen that did not exist.
 * This is the real screen behind that name, and it is a real working surface,
 * which is the only rule §3 actually froze.
 *
 * Three rules this screen holds to, because a spend switch is not a checkbox:
 *
 *  1. **The cost is visible before the decision, not after.** It names the exact
 *     routes that switching ON would unlock. A switch whose consequence is
 *     hidden is a switch nobody should flip.
 *  2. **It reports the STORED state.** The mutation writes what the server
 *     returned, never what the click hoped for, so a refused write cannot leave
 *     the switch looking on.
 *  3. **A missing provider key is stated plainly.** Turning paid routes on while
 *     `OPENROUTER_API_KEY` is absent enables nothing, and saying "on" then would
 *     be a lie about the system's state.
 */

/** Role names in the editor's words; anything unknown falls back to the raw id. */
const ROLE_LABELS: Record<string, string> = {
  judge: "Проверка (judge)",
  story: "Идентичност на история",
  angle: "Ъгъл",
  draft: "Финален текст",
  research: "Проучване",
  extract: "Извличане на факти",
  utility: "Помощни задачи",
};

export function ModelsSettingsPage() {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: queryKeys.modelSettings,
    queryFn: getModelSettings,
  });
  // The editor's own draft of the budget, seeded from what is stored. It is
  // only SENT when it differs, so opening this screen and leaving writes
  // nothing at all.
  const [budget, setBudget] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: (input: { paidEnabled: boolean; softPaidBudgetUsdDay?: number }) =>
      setPaidModels(input),
    onSuccess: (stored) => {
      // The server's stored state becomes the screen's state — never the click.
      queryClient.setQueryData(queryKeys.modelSettings, stored);
      setBudget(null);
    },
  });

  const settings = query.data;

  function toggle() {
    if (!settings) return;
    save.mutate({ paidEnabled: !settings.paidEnabled });
  }

  // V1.2-G4.41. A budget the operator cannot read is a budget they think they
  // saved. `saveBudget` used to `return` silently on a value it could not use,
  // so typing "abc" or "-5" and pressing the button did nothing at all — on a
  // SPEND field, where a silent no-op is indistinguishable from a successful
  // save. The refusal is now computed and shown, and the button is disabled
  // while the value is unusable, so the reason is on screen before the click
  // rather than after it.
  function budgetProblem(): string {
    if (budget === null) return "";
    const raw = budget.trim();
    if (raw === "") return "Въведи число.";
    const parsed = Number(raw);
    if (!Number.isFinite(parsed)) return "Бюджетът трябва да е число.";
    if (parsed < 0) return "Бюджетът не може да е отрицателен.";
    if (parsed > 500) return "Бюджетът не може да е над 500 USD.";
    return "";
  }

  function saveBudget() {
    if (!settings || budgetProblem()) return;
    save.mutate({
      paidEnabled: settings.paidEnabled,
      softPaidBudgetUsdDay: Number(budget!.trim()),
    });
  }

  const header = (
    <PageHeader
      kicker="Настройки"
      title="AI и модели"
      lede="Кои модели може да използва редакцията. Платените модели са изключени по подразбиране; включването им реално харчи пари."
    />
  );

  // Each state RETURNS rather than being guarded in place. A `{data && (…)}`
  // block wrapped three screens of JSX, and the automatic JSX runtime hoists
  // static children out of the conditional — so the guard was not the boundary
  // it looked like, and the block's own `data.keys` read ran on the loading
  // render. An early return is both correct and the shape of every other page
  // here.
  if (query.isLoading) {
    return <div className={styles.page}>{header}<LoadingState label="Зареждане…" /></div>;
  }
  if (query.isError) {
    return (
      <div className={styles.page}>
        {header}
        <ErrorState
          title="Настройките на моделите не можа да се заредят"
          error={query.error}
          onRetry={() => void query.refetch()}
        />
      </div>
    );
  }
  if (!settings) {
    // Nothing read yet and nothing failed. Not a state the editor should be
    // shown, and not a blank page either.
    return <div className={styles.page}>{header}<LoadingState label="Зареждане…" /></div>;
  }

  return (
    <div className={styles.page}>
      {header}
      <>
          <Section title="Платени модели">
            <div className={styles.switchRow}>
              <label className={styles.switchLabel} htmlFor="paid-enabled">
                <input
                  id="paid-enabled"
                  type="checkbox"
                  checked={settings.paidEnabled}
                  disabled={save.isPending}
                  onChange={toggle}
                />
                Разреши платени модели
              </label>
              <span className={styles.state} data-on={settings.paidEnabled}>
                {settings.paidEnabled ? "Разрешени" : "Забранени"}
              </span>
            </div>

            {!settings.keys.openrouter && (
              <p className={styles.warn}>
                В този процес няма <code>OPENROUTER_API_KEY</code>. Включването на
                платените модели няма да даде достъп до тях, защото няма ключ.
              </p>
            )}
            {settings.paidSoftExceeded && (
              <p className={styles.warn}>
                Дневният меж разход е надхвърлил софт бюджета. Маршрутизирането
                продължава — това е предупреждение, не блокиране.
              </p>
            )}

            <dl className={styles.facts}>
              <div>
                <dt>Платено днес</dt>
                <dd>${settings.paidCostTodayUsd.toFixed(4)}</dd>
              </div>
              <div>
                <dt>Софт бюджет на ден</dt>
                <dd>${settings.softPaidBudgetUsdDay.toFixed(2)}</dd>
              </div>
              <div>
                <dt>Ден</dt>
                <dd>{settings.day}</dd>
              </div>
            </dl>

            <div className={styles.budgetRow}>
              <label htmlFor="paid-budget">Нов софт бюджет на ден (USD)</label>
              <input
                id="paid-budget"
                type="number"
                min={0}
                max={500}
                step="0.5"
                aria-invalid={Boolean(budgetProblem())}
                aria-describedby={budgetProblem() ? "paid-budget-problem" : undefined}
                value={budget ?? String(settings.softPaidBudgetUsdDay)}
                onChange={(event) => setBudget(event.target.value)}
              />
              <button
                type="button"
                className={styles.secondary}
                disabled={save.isPending || budget === null || Boolean(budgetProblem())}
                onClick={saveBudget}
              >
                Запази бюджета
              </button>
            </div>
            {budgetProblem() ? (
              <p className={styles.warn} id="paid-budget-problem" role="alert">
                {budgetProblem()}
              </p>
            ) : null}

            {save.isError && (
              <p className={styles.error} role="alert">
                {getErrorMessage(save.error, "Настройката не можа да се запази.")}
              </p>
            )}
          </Section>

          <Section title="Какво се отключва">
            {settings.paidRoutes.length === 0 ? (
              <p className={styles.muted}>
                Политиката не декларира платени маршрути. Включването на превключвателя
                няма какво да отключи.
              </p>
            ) : (
              <ul className={styles.routes}>
                {settings.paidRoutes.map((route) => (
                  <li key={`${route.role}:${route.provider}:${route.model}`}>
                    <strong>{ROLE_LABELS[route.role] ?? route.role}</strong>
                    <span className={styles.routeModel}>
                      {route.provider}:{route.model}
                    </span>
                    {!settings.paidEnabled && (
                      <span className={styles.locked}>заключен</span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Section>

          <Section title="Маршрути по роля">
            <table className={styles.roles}>
              <thead>
                <tr>
                  <th>Роля</th>
                  <th>Достъпни</th>
                  <th>От всички</th>
                  <th>При изчерпване</th>
                </tr>
              </thead>
              <tbody>
                {settings.roles.map((role) => (
                  <tr key={role.role} data-dead={role.eligible === 0}>
                    <td>{ROLE_LABELS[role.role] ?? role.role}</td>
                    <td>{role.eligible}</td>
                    <td>{role.total}</td>
                    <td>{role.onExhausted}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {settings.roles.some((role) => role.eligible === 0) && (
              <p className={styles.warn}>
                Роля без достъпен маршрут не може да върши работа. Това не се
                поправя с платения превключвател — липсващ ключ е друг проблем.
              </p>
            )}
          </Section>
      </>
    </div>
  );
}
