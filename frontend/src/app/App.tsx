import { BrowserRouter, Route, Routes } from "react-router-dom";
import { AppErrorBoundary } from "./AppErrorBoundary";
import { AppShell } from "./AppShell";
import { QueryProvider } from "./QueryProvider";
import { ArticleWorkspace } from "../pages/ArticleWorkspace";
import { ArticleListPage } from "../pages/ArticleListPage";
import { ArchivePage } from "../pages/ArchivePage";
import { FeedbackSettingsPage } from "../pages/FeedbackSettingsPage";
import { FinalizedArticleView } from "../pages/FinalizedArticleView";
import { SettingsLanding } from "../pages/SettingsLanding";
import { SourcesPage } from "../pages/SourcesPage";
import { StoryWorkspace } from "../pages/StoryWorkspace";
import { StoryListPage } from "../pages/StoryListPage";
import { TodayPage } from "../pages/TodayPage";
import { NotFoundPage } from "../pages/NotFoundPage";
import { OperationsPage } from "../pages/OperationsPage";

export function App() {
  return <AppErrorBoundary>
    <QueryProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<TodayPage />} />
            <Route path="stories" element={<StoryListPage />} />
            <Route path="stories/:storyId" element={<StoryWorkspace />} />
            <Route path="articles" element={<ArticleListPage />} />
            <Route path="articles/:articleId" element={<ArticleWorkspace />} />
            <Route path="operations" element={<OperationsPage />} />
            <Route path="archive" element={<ArchivePage />} />
            <Route path="archive/:articleId" element={<FinalizedArticleView />} />
            <Route path="settings" element={<SettingsLanding />} />
            {/* V1.2-G4 §3: `Настройки` stays in the left rail; `Източници` is the
                one secondary screen this slice makes real. `AI и модели` and
                `Система` stay unimplemented rather than shipping as empty tabs. */}
            <Route path="settings/sources" element={<SourcesPage />} />
            {/* V1.2-G4.3 §G: the controlled learning loop, now reachable from the
                editor's own Settings rather than only from a terminal. */}
            <Route path="settings/feedback" element={<FeedbackSettingsPage />} />
            <Route path="*" element={<NotFoundPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryProvider>
  </AppErrorBoundary>;
}
