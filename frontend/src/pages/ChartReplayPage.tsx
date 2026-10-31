import { lazy, Suspense } from "react";
const ChartReplayWorkspace = lazy(() => import("../components/ChartReplayWorkspace").then(module => ({ default: module.ChartReplayWorkspace })));

export function ChartReplayPage() {
  return <main className="pageShell semiPage replayPage">
    <header className="semiHero"><div><p className="eyebrow">MARKET REPLAY</p><h1>시간을 맞추고, 흐름을 비교하세요</h1><p>코스피 2022년과 금 2024년처럼 서로 다른 시기의 차트를 홈페이지에서 직접 재생합니다.</p></div></header>
    <Suspense fallback={<p role="status">차트 작업 공간을 불러오는 중…</p>}><ChartReplayWorkspace /></Suspense>
  </main>;
}
