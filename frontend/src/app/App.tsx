import { BrowserRouter, Route, Routes } from "react-router-dom";
import { AppErrorBoundary } from "./AppErrorBoundary";
import { AppShell } from "./AppShell";
import { QueryProvider } from "./QueryProvider";
import { ArticleWorkspace } from "../pages/ArticleWorkspace";
import { ArticleListPage } from "../pages/ArticleListPage";
import { ArchivePage } from "../pages/ArchivePage";
import { FinalizedArticleView } from "../pages/FinalizedArticleView";
import { SettingsLanding } from "../pages/SettingsLanding";
import { StoryWorkspace } from "../pages/StoryWorkspace";
import { StoryListPage } from "../pages/StoryListPage";
import { TodayPage } from "../pages/TodayPage";
import { NotFoundPage } from "../pages/NotFoundPage";

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
            <Route path="archive" element={<ArchivePage />} />
            <Route path="archive/:articleId" element={<FinalizedArticleView />} />
            <Route path="settings" element={<SettingsLanding />} />
            <Route path="*" element={<NotFoundPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryProvider>
  </AppErrorBoundary>;
}
