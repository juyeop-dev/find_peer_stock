import { useEffect, useRef, useState } from "react";
import { tradingViewUrl } from "../dataClient/stockDetailLinks";

interface Props { symbol: string; kind: "chart" | "financials" }

// Official embed contracts:
// https://www.tradingview.com/widget-docs/widgets/charts/advanced-chart/
// https://www.tradingview.com/widget-docs/widgets/symbol-details/fundamental-data/
export function TradingViewWidget({ symbol, kind }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const host = container.current;
    if (!host) return;
    let alive = true;
    setStatus("loading");
    const wrapper = document.createElement("div");
    wrapper.className = "tradingview-widget-container";
    const widget = document.createElement("div");
    widget.className = "tradingview-widget-container__widget";
    wrapper.appendChild(widget);
    const script = document.createElement("script");
    script.src = `https://s3.tradingview.com/external-embedding/embed-widget-${kind === "chart" ? "advanced-chart" : "financials"}.js`;
    script.async = true;
    script.textContent = JSON.stringify(kind === "chart" ? {
      autosize: true, symbol, interval: "D", timezone: "exchange", theme: "light", style: "1",
      locale: "kr", allow_symbol_change: false, withdateranges: true, hide_side_toolbar: true,
      hide_top_toolbar: false, save_image: false, calendar: false, support_host: "https://www.tradingview.com",
    } : { symbol, colorTheme: "light", displayMode: "regular", isTransparent: false, locale: "kr", width: "100%", height: "100%" });
    const fail = () => {
      if (alive) { setStatus("error"); host.replaceChildren(); }
    };
    script.onerror = fail;
    const timeout = window.setTimeout(fail, 25_000);
    const observer = new MutationObserver(() => {
      for (const iframe of wrapper.querySelectorAll("iframe")) {
        if (iframe.dataset.observed) continue;
        iframe.dataset.observed = "true";
        iframe.loading = "eager";
        iframe.title = `${symbol} ${kind === "chart" ? "주가 차트" : "기업 실적 및 투자 지표"}`;
        iframe.addEventListener("load", () => {
          if (alive) { window.clearTimeout(timeout); setStatus("ready"); }
        }, { once: true });
        iframe.addEventListener("error", fail, { once: true });
      }
    });
    observer.observe(wrapper, { childList: true, subtree: true });
    host.replaceChildren(wrapper);
    wrapper.appendChild(script);
    return () => {
      alive = false;
      window.clearTimeout(timeout);
      observer.disconnect();
      script.onerror = null;
      host.replaceChildren();
    };
  }, [symbol, kind, attempt]);

  return <div className={`marketWidget marketWidget-${kind}`}>
    {status === "loading" ? <p className="marketWidgetLoading" role="status">{kind === "chart" ? "주가 차트" : "기업 실적"}를 불러오고 있습니다.</p> : null}
    <div ref={container} className="marketWidgetHost" aria-busy={status === "loading"} hidden={status === "error"} />
    {status === "error" ? <div className="marketWidgetError" role="status"><strong>외부 자료를 불러오지 못했습니다.</strong>
      <p>아래 외부 시세 링크에서도 종목 정보를 확인할 수 있습니다.</p><button type="button" onClick={() => setAttempt((value) => value + 1)}>다시 불러오기</button></div> : null}
    <div className="tradingview-widget-copyright"><a href={`${tradingViewUrl(symbol)}${kind === "financials" ? "financials-overview/" : ""}`}
      target="_blank" rel="noopener nofollow noreferrer">{symbol} {kind === "chart" ? "chart" : "fundamentals"}</a><span> by TradingView</span></div>
  </div>;
}
