import { Link } from "react-router-dom";
import type { CompanyProfile } from "../dataClient/types";

interface StockHeaderProps {
  company: CompanyProfile;
}

export function StockHeader({ company }: StockHeaderProps) {
  return (
    <header className="stockHeader">
      <div>
        <Link className="backLink" to="/">
          전체 종목
        </Link>
        <h1>{company.name_kr}</h1>
        <div className="stockMeta">
          <span>{company.ticker}</span>
          <span>{company.country}</span>
          <span>{company.theme}</span>
        </div>
      </div>
    </header>
  );
}
