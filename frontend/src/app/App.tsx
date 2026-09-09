import { Navigate, NavLink, Route, Routes } from "react-router-dom";
import { HomePage } from "../pages/HomePage";
import { StockPage } from "../pages/StockPage";
import { NewHighPage } from "../pages/NewHighPage";
import "../styles/newHighs.css";

export function App() {
  return (
    <>
      <nav className="siteNav" aria-label="주 메뉴">
        <NavLink className="siteBrand" to="/">STOCK PEER<span>마켓 노트</span></NavLink>
        <div className="siteNavLinks">
          <NavLink to="/" end>Peer 비교</NavLink>
          <NavLink to="/new-highs">신고가 캘린더</NavLink>
        </div>
      </nav>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/stocks/:ticker" element={<StockPage />} />
        <Route path="/new-highs" element={<NewHighPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  );
}
