// Official Advanced Chart widget configuration, not the separately licensed library.
// https://www.tradingview.com/widget-docs/widgets/charts/advanced-chart/demos/technical-analysis/
// https://www.tradingview.com/widget-docs/widgets/charts/advanced-chart/demos/analytics-platform/
export function tradingViewChartOptions(symbol: string) {
  return {
    autosize: true, symbol, interval: "D", range: "12M", timezone: "exchange", theme: "light", style: "1",
    locale: "kr", allow_symbol_change: true, withdateranges: true,
    hide_side_toolbar: false, hide_top_toolbar: false, save_image: true,
    details: true, hotlist: true, watchlist: [symbol],
    show_popup_button: true, popup_width: "1280", popup_height: "800",
    support_host: "https://www.tradingview.com",
  };
}
export function tradingViewChartUrl(symbol: string): string {
  return `https://www.tradingview.com/chart/?symbol=${encodeURIComponent(symbol)}`;
}
// Verified against the provider's KRX widget response; keep an actual usable chart.
// https://www.tradingview.com/widget-docs/faq/data/#what-does-this-symbol-is-only-available-on-tradingview-message-mean
export const tradingViewWidgetRestricted = (symbol: string | null) => symbol?.startsWith("KRX:") ?? false;
