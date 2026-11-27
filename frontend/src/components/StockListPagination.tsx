import { useState } from "react";

const PAGE_SIZE = 30;

export function useStockList<T>(stocks: readonly T[], view = "") {
  const [page, setPage] = useState({ view, limit: PAGE_SIZE });
  const limit = page.view === view ? page.limit : PAGE_SIZE;
  if (page.view !== view) setPage({ view, limit });

  const visible = stocks.slice(0, limit);
  return {
    visible,
    more: {
      remaining: stocks.length - visible.length,
      onClick: () => setPage(current => ({ view, limit: (current.view === view ? current.limit : PAGE_SIZE) + PAGE_SIZE })),
    },
  };
}

export function MoreStocks({ remaining, onClick }: { remaining: number; onClick: () => void }) {
  if (!remaining) return null;
  return <button type="button" className="stockListMore" onClick={onClick} aria-label={`${Math.min(remaining, PAGE_SIZE)}개 종목 더 보기`}>더 보기</button>;
}
