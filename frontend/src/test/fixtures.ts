
import type { ArticleFilter } from "../api/client";
import type { FinalizeResult } from "../api/client";
import type {
  ArchiveArticle,
  ArticleDetail,
  FactAndSource,
  StoryDetail,
  TodayProjection,
} from "../api/dto";

export const activeArticleFilters: readonly ArticleFilter[] = ["preparation", "draft", "ready"];

const factsAndSources: FactAndSource[] = [
  {
    id: "fact-budget-1",
    text: "Общинският съвет отдели 420 000 лева за обслужването на детските градини през следващата учебна година.",
    source: {
      id: "source-council",
      name: "Официален портал на Общинския съвет",
      domain: "burgascouncil.org",
      url: "https://burgascouncil.org/budget-2026",
      locator: "Решение № 18",
    },
    locator: "т. 4",
    scope: "current",
  },
  {
    id: "fact-source-1",
    text: "Промяната влезе в сила след публикуване в Държавен вестник.",
    source: { id: "source-venetsanie", name: "Държавен вестник", domain: "dv.parliament.bg" },
    locator: "бр. 72",
    scope: "background",
  },
];

const latestStoryDevelopment: NonNullable<StoryDetail["latestDevelopment"]> = {
  id: "development-budget-2",
  publicationId: "publication-budget-2",
  title: "Съветът прие бюджета за детските градини",
  summary: "Решението предвижда 420 000 лева допълнително финансиране за следващата учебна година.",
  changedAt: "2026-09-25T09:30:00Z",
  unreviewed: true,
};

export const storyDetail: StoryDetail = {
  id: "story-sunche-vo",
  title: "Общинският съвет увеличи бюджета за детските градини в Слънчево",
  summary: "След обсъждане на предложението за бюджета училищата ще получат допълнителни средства за поддръжка.",
  reviewed: true,
  ignored: false,
  followed: true,
  hasNewDevelopment: true,
  unreviewedDevelopmentCount: 2,
  latestDevelopment: latestStoryDevelopment,
  latestChangeAt: "2026-09-25T09:30:00Z",
  availableActions: ["REVIEW", "UNFOLLOW", "IGNORE", "START_ARTICLE"],
  nextAction: {
    action: "REVIEW",
    reasonCode: "UNREVIEWED_DEVELOPMENT",
    label: "Прегледай",
    primary: true,
  },
  whatHappened:
    "Общинският съвет прие промяна в бюджета, с която се увеличава финансирането на детските градини в Слънчево. Решението влиза в сила след официалното му публикуване.",
  publications: [
    {
      id: "publication-budget-1",
      title: "Първоначално предложение за бюджета",
      source: { id: "source-council", name: "Официален портал на Общинския съвет", domain: "burgascouncil.org" },
      url: "https://burgascouncil.org/budget-2026/proposal",
      publishedAt: "2026-09-20T08:00:00Z",
      discoveredAt: "2026-09-20T08:05:00Z",
      summary: "Публично предложение за увеличаване на средствата за градините.",
      factsAndSourceIds: ["fact-budget-1"],
    },
    {
      id: "publication-budget-2",
      title: "Съветът прие бюджета за детските градини",
      source: { id: "source-council", name: "Официален портал на Общинския съвет", domain: "burgascouncil.org" },
      url: "https://burgascouncil.org/budget-2026/final",
      publishedAt: "2026-09-25T09:30:00Z",
      discoveredAt: "2026-09-25T09:31:00Z",
      summary: "Официалното решение на Общинския съвет.",
      factsAndSourceIds: ["fact-budget-1", "fact-source-1"],
    },
  ],
  chronology: [
    { publicationId: "publication-budget-1", at: "2026-09-20T08:00:00Z", kind: "EVENT", title: "Публикувано първоначално предложение" },
    { publicationId: "publication-budget-2", at: "2026-09-25T09:30:00Z", kind: "NEW_DEVELOPMENT", title: "Приет е окончателният бюджет" },
  ],
  newDevelopments: [
    {
      id: "development-budget-1",
      publicationId: "publication-budget-1",
      title: "Публикувано е предложение за бюджета",
      summary: "Предложението предвижда допълнително финансиране на градините.",
      changedAt: "2026-09-20T08:00:00Z",
      unreviewed: false,
    },
    latestStoryDevelopment,
  ],
  relatedArticles: [{ id: "article-budget-draft", title: "Ремонтът на булевард „Свобода“ ще започне през октомври" }],
  factsAndSources,
  missingInformation: {
    assessedAt: "2026-09-25T09:32:00Z",
    items: [
      {
        id: "gap-contract-date",
        question: "Кога започва изпълнението на договора за ремонта?",
        kind: "missing_fact",
        blocking: false,
        reason: "Общинският портал все още не е публикувал графика.",
      },
    ],
  },
  correction: { available: true, actions: ["DETACH_PUBLICATION", "MERGE_STORY"] },
};

function articleBase(): Omit<ArticleDetail, "state" | "content" | "readiness" | "availableActions" | "nextAction" | "isFinalized" | "finalizedAt"> {
  return {
    id: "article-budget-draft",
    title: "Ремонтът на булевард „Свобода“ ще започне през октомври",
    story: { id: storyDetail.id, title: storyDetail.title },
    editorialFocus: {
      text: "Показваме какво е готово по ремонта и какво още трябва да бъде уточнено с община Бургас.",
      confirmedAt: "2026-09-25T09:40:00Z",
    },
    warnings: [],
    validation: {
      contentVersion: 0,
      current: true,
      blocking: false,
      readyEligible: false,
    },
    createdAt: "2026-09-25T09:35:00Z",
    updatedAt: "2026-09-25T09:40:00Z",
    factsAndSources,
    missingInformation: storyDetail.missingInformation!,
    preparation: null,
  };
}

export const activePreparationArticle: ArticleDetail = {
  ...articleBase(),
  id: "article-budget-preparation",
  title: "Ремонтът на булевард „Свобода“ — какво предстои",
  state: "preparation",
  editorialFocus: { text: "Показваме какво е готово по ремонта и какво още трябва да бъде уточнено с община Бургас.", confirmedAt: null },
  content: { title: "Ремонтът на булевард „Свобода“ — какво предстои", body: "", version: 0 },
  preparation: {
    focusConfirmed: false,
    blockingGaps: [],
    nonBlockingGaps: [storyDetail.missingInformation!.items[0]!],
    draftEligible: false,
    availableActions: ["SELECT_FOCUS"],
  },
  readiness: { isCurrent: false, readyVersion: null, readyAt: null },
  availableActions: ["SELECT_FOCUS"],
  nextAction: { action: "SELECT_FOCUS", reasonCode: "FOCUS_REQUIRED", label: "Избери фокус", primary: true },
  isFinalized: false,
  finalizedAt: null,
};

export const activeDraftArticle: ArticleDetail = {
  ...articleBase(),
  state: "draft",
  content: {
    title: "Ремонтът на булевард „Свобода“ ще започне през октомври",
    body: "Според община Бургас ремонтът на булевард „Свобода“ е планиран да започне през октомври. Очаква се движението в района да бъде ограничено, а точната дата да бъде публикувана в официалния график.",
    version: 3,
  },
  validation: {
    contentVersion: 3,
    current: true,
    blocking: false,
    readyEligible: true,
  },
  readiness: { isCurrent: false, readyVersion: null, readyAt: null },
  availableActions: ["EDIT", "MARK_READY"],
  nextAction: { action: "MARK_READY", reasonCode: "READY_ELIGIBLE", label: "Отбележи като готова", primary: true },
  isFinalized: false,
  finalizedAt: null,
};

export const activeReadyArticle: ArticleDetail = {
  ...activeDraftArticle,
  id: "article-budget-ready",
  title: "Общинският съвет увеличи бюджета за детските градини в Слънчево",
  state: "ready",
  content: {
    title: "Общинският съвет увеличи бюджета за детските градини в Слънчево",
    body: "Общинският съвет прие решение за допълнително финансиране на детските градини в Слънчево. Средствата са предназначени за обслужване на сгради и текущи разходи през следващата учебна година.",
    version: 4,
  },
  validation: { contentVersion: 4, current: true, blocking: false, readyEligible: false },
  readiness: { isCurrent: true, readyVersion: 4, readyAt: "2026-09-25T10:00:00Z" },
  // C5 completes the Ready surface: exactly the two editorial decisions.
  availableActions: ["EDIT", "FINALIZE"],
  nextAction: {
    action: "FINALIZE",
    reasonCode: "READY_TO_FINALIZE",
    label: "Финализирай",
    primary: true,
  },
  updatedAt: "2026-09-25T10:00:00Z",
};

export const todayProjection: TodayProjection = {
  newDevelopments: [
    {
      objectId: "story-sunche-vo",
      objectType: "story",
      title: storyDetail.title,
      summary: "Съветът прие бюджета за детските градини.",
      timestamp: "2026-09-25T09:30:00Z",
      reason: "UNREVIEWED_DEVELOPMENT",
      nextAction: "REVIEW",
      delta: { unreviewedDevelopmentCount: 2 },
    },
  ],
  newStories: [
    {
      objectId: "story-pomorie",
      objectType: "story",
      title: "Община Поморие отвори център за подкрепа на семействата с деца с диабет",
      summary: "Новата услуга ще консултира семейства и ще насочва към медицинска грижа.",
      timestamp: "2026-09-25T08:10:00Z",
      reason: "NEW_STORY",
      nextAction: "REVIEW",
      delta: { unreviewedDevelopmentCount: 0 },
    },
  ],
  articlesRequiringAction: [
    {
      objectId: activeDraftArticle.id,
      objectType: "article",
      title: activeDraftArticle.title,
      summary: "Има запазена чернова, която очаква редакторска проверка.",
      timestamp: activeDraftArticle.updatedAt,
      reason: "DRAFT",
      nextAction: activeDraftArticle.nextAction!,
    },
    // A `Готова` Article has no next action in C4, so it does not ask for one
    // in Today either.
  ],
  problems: [
    {
      id: "transport-source-unavailable",
      title: "Официалната страница на транспортната програма не можа да бъде заредена.",
      consequence: "Промяната в маршрута 12 очаква потвърждение.",
      label: "Липсва потвърждение",
      target: "/settings/sources",
    },
  ],
};

export const finalizedArchiveArticle: ArchiveArticle = {
  ...activeReadyArticle,
  id: "article-budget-archive",
  title: "Общинският съвет увеличи бюджета за обслужване на детските градини",
  content: {
    title: "Общинският съвет увеличи бюджета за обслужване на детските градини",
    body: "Решението на Общинския съвет влиза в сила след публикуване в Държавен вестник.",
    version: 5,
  },
  readiness: { isCurrent: true, readyVersion: 5, readyAt: "2026-09-24T16:20:00Z" },
  state: null,
  isFinalized: true,
  finalizedAt: "2026-09-24T16:30:00Z",
  // The Archive is read-only: no edit, no finalize, no publish, no reopen.
  availableActions: [],
  nextAction: null,
};

/** The canonical `Финализирай` response: the frozen Article and where it lives. */
export const finalizeResult: FinalizeResult = {
  articleId: finalizedArchiveArticle.id,
  archivePath: `/archive/${finalizedArchiveArticle.id}`,
  finalizedAt: finalizedArchiveArticle.finalizedAt,
  article: finalizedArchiveArticle,
};


