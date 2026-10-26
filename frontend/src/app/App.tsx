import { Navigate, NavLink, Route, Routes } from "react-router-dom";
import { HomePage } from "../pages/HomePage";
import { StockPage } from "../pages/StockPage";
import { NewHighPage } from "../pages/NewHighPage";
import { TurnoverPage } from "../pages/TurnoverPage";
import { SemiconductorPage } from "../pages/SemiconductorPage";
import { SemiconductorTrendsPage } from "../pages/SemiconductorTrendsPage";
import { SemiconductorStockPage } from "../pages/SemiconductorStockPage";
import { CreditBalancePage } from "../pages/CreditBalancePage";
import { CalendarHistoryPage } from "../pages/CalendarHistoryPage";
import { MarketStockPage } from "../pages/MarketStockPage";
import { SectorRankingsPage } from "../pages/SectorRankingsPage";
import { SectorExplorerPage } from "../pages/SectorExplorerPage";
import "../styles/newHighs.css";
import "../styles/semiconductor.css";

export function App() {
  return (
    <>
      <nav className="siteNav" aria-label="주 메뉴">
        <NavLink className="siteBrand" to="/">STOCK PEER<span>마켓 노트</span></NavLink>
        <div className="siteNavLinks">
          <NavLink to="/" end>Peer 비교</NavLink>
          <NavLink to="/new-highs">신고가 캘린더</NavLink>
          <NavLink to="/turnover">거래대금 캘린더</NavLink>
          <NavLink to="/calendar-history">누적 기록</NavLink>
          <NavLink to="/sector-stocks">섹터별 종목</NavLink>
          <NavLink to="/sectors">섹터 상승률</NavLink>
          <NavLink to="/sector-trends">섹터별 추이</NavLink>
          <NavLink to="/credit-balance">신용 잔고</NavLink>
        </div>
      </nav>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/stocks/:ticker" element={<StockPage />} />
        <Route path="/market-stocks/:ticker" element={<MarketStockPage />} />
        <Route path="/new-highs" element={<NewHighPage />} />
        <Route path="/turnover" element={<TurnoverPage />} />
        <Route path="/calendar-history" element={<CalendarHistoryPage />} />
        <Route path="/sectors" element={<SectorRankingsPage />} />
        <Route path="/semiconductors" element={<SectorExplorerPage mode="stocks" semiconductor={<SemiconductorPage />} />} />
        <Route path="/semiconductors/trends" element={<SectorExplorerPage mode="trends" semiconductor={<SemiconductorTrendsPage />} />} />
        <Route path="/sector-stocks" element={<SectorExplorerPage mode="stocks" semiconductor={<SemiconductorPage />} />} />
        <Route path="/sector-trends" element={<SectorExplorerPage mode="trends" semiconductor={<SemiconductorTrendsPage />} />} />
        <Route path="/semiconductors/:ticker" element={<SemiconductorStockPage />} />
        <Route path="/credit-balance" element={<CreditBalancePage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  );
}
