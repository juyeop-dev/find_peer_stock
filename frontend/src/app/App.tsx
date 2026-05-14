import { Navigate, Route, Routes } from "react-router-dom";
import { HomePage } from "../pages/HomePage";
import { StockPage } from "../pages/StockPage";

export function App() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/stocks/:ticker" element={<StockPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
