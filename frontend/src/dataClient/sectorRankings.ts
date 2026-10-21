export type SectorPeriod = "day" | "week" | "month" | "quarter" | "year";
export type SectorLevel = "sector" | "industry";
export type SectorSort = "return" | "turnover" | "marketCap" | "count";
export const SECTOR_PERIODS: { key: SectorPeriod; label: string }[] = [
  { key: "day", label: "오늘" }, { key: "week", label: "1주" }, { key: "month", label: "1개월" }, { key: "quarter", label: "3개월" }, { key: "year", label: "1년" },
];
export interface SectorStock {
  ticker: string; code: string; name: string; exchange: "KOSPI" | "KOSDAQ"; sector: string; industry: string;
  currency: "KRW"; price: number; change_pct: number | null; turnover: number | null; market_cap: number | null; date: string;
  returns: Record<SectorPeriod, number | null>;
}
export interface SectorSnapshot {
  schema_version: 1; market: "korea"; currency: "KRW"; date: string; fetched_at: string; source: string; source_url: string;
  universe: string; received: number; excluded: Record<string, number>; stale_count: number; stocks: SectorStock[];
  source_fetched_at?: string;
  archived?: boolean;
}
export interface SectorCalendarRecord { date: string; fetched_at: string; count: number; industries: number }
export interface SectorCalendar { schema_version: 1; market: "korea"; latest_date: string; records: SectorCalendarRecord[] }
export interface SectorRanking {
  key: string; name: string; sector: string; members: SectorStock[]; representative: SectorStock;
  value: number | null; returnCount: number; turnover: number | null; turnoverCount: number; marketCap: number | null; capCount: number;
}

const LABELS: Record<string, string> = {
  "Commercial Services": "사업 서비스", "Communications": "통신", "Consumer Durables": "내구소비재", "Consumer Non-Durables": "필수소비재",
  "Consumer Services": "소비자 서비스", "Distribution Services": "유통", "Electronic Technology": "전자·반도체", "Energy Minerals": "에너지",
  "Finance": "금융", "Health Services": "의료 서비스", "Health Technology": "제약·바이오·의료기기", "Industrial Services": "산업 서비스",
  "Miscellaneous": "기타", "Non-Energy Minerals": "철강·비철금속", "Process Industries": "소재·화학", "Producer Manufacturing": "산업재·제조",
  "Retail Trade": "소매", "Technology Services": "IT 서비스", "Transportation": "운송", "Utilities": "전력·가스", "Unclassified": "미분류",
  "Advertising/Marketing Services": "광고·마케팅", "Aerospace & Defense": "항공우주·방산", "Agricultural Commodities/Milling": "농산물·제분",
  "Air Freight/Couriers": "항공화물·택배", "Airlines": "항공", "Alternative Power Generation": "대체에너지 발전", "Aluminum": "알루미늄",
  "Apparel/Footwear": "의류·신발", "Apparel/Footwear Retail": "의류·신발 소매", "Auto Parts: OEM": "자동차 부품", "Automotive Aftermarket": "자동차 정비·보수",
  "Beverages: Alcoholic": "주류", "Beverages: Non-Alcoholic": "음료", "Biotechnology": "바이오", "Broadcasting": "방송", "Building Products": "건축 자재",
  "Cable/Satellite TV": "케이블·위성방송", "Casinos/Gaming": "카지노·게임", "Chemicals: Agricultural": "농업용 화학", "Chemicals: Major Diversified": "종합 화학",
  "Chemicals: Specialty": "정밀 화학", "Coal": "석탄", "Commercial Printing/Forms": "인쇄", "Computer Communications": "컴퓨터 통신",
  "Computer Peripherals": "컴퓨터 주변기기", "Computer Processing Hardware": "컴퓨터 하드웨어", "Construction Materials": "건설 소재", "Consumer Sundries": "생활용품",
  "Containers/Packaging": "용기·포장", "Data Processing Services": "데이터 처리", "Department Stores": "백화점", "Drugstore Chains": "의약품 소매",
  "Electric Utilities": "전력", "Electrical Products": "전기 장비", "Electronic Components": "전자 부품", "Electronic Equipment/Instruments": "전자 기기·계측",
  "Electronic Production Equipment": "전자 생산장비", "Electronics Distributors": "전자제품 유통", "Electronics/Appliance Stores": "가전 소매", "Electronics/Appliances": "가전제품",
  "Engineering & Construction": "건설·엔지니어링", "Environmental Services": "환경 서비스", "Finance/Rental/Leasing": "금융·렌탈·리스",
  "Financial Conglomerates": "금융 지주", "Financial Publishing/Services": "금융정보 서비스", "Food Distributors": "식품 유통", "Food Retail": "식품 소매",
  "Food: Major Diversified": "종합 식품", "Food: Meat/Fish/Dairy": "축산·수산·유제품", "Food: Specialty/Candy": "가공식품·제과", "Forest Products": "임산물",
  "Gas Distributors": "가스 공급", "Home Furnishings": "가구·인테리어", "Home Improvement Chains": "주택용품 소매", "Homebuilding": "주택 건설",
  "Hotels/Resorts/Cruise lines": "호텔·리조트", "Household/Personal Care": "생활용품·화장품", "Industrial Conglomerates": "산업 지주", "Industrial Machinery": "산업 기계",
  "Industrial Specialties": "산업 특수제품", "Information Technology Services": "IT 서비스", "Insurance Brokers/Services": "보험 중개·서비스", "Integrated Oil": "종합 석유",
  "Internet Retail": "인터넷 쇼핑", "Internet Software/Services": "인터넷 서비스", "Investment Banks/Brokers": "증권", "Investment Managers": "자산 운용",
  "Investment Trusts/Mutual Funds": "투자회사", "Life/Health Insurance": "생명·건강보험", "Major Banks": "대형 은행", "Major Telecommunications": "종합 통신",
  "Marine Shipping": "해운", "Medical Distributors": "의료 유통", "Medical Specialties": "의료 기기", "Medical/Nursing Services": "의료·간호 서비스",
  "Metal Fabrication": "금속 가공", "Miscellaneous Commercial Services": "기타 사업 서비스", "Miscellaneous Manufacturing": "기타 제조", "Motor Vehicles": "자동차",
  "Movies/Entertainment": "영화·엔터테인먼트", "Multi-Line Insurance": "종합 보험", "Office Equipment/Supplies": "사무 기기·용품", "Oil Refining/Marketing": "정유",
  "Other Consumer Services": "기타 소비자 서비스", "Other Consumer Specialties": "기타 소비재", "Other Metals/Minerals": "기타 금속·광물", "Other Transportation": "기타 운송",
  "Packaged Software": "소프트웨어", "Pharmaceuticals: Generic": "복제약", "Pharmaceuticals: Major": "주요 제약", "Pharmaceuticals: Other": "기타 제약",
  "Property/Casualty Insurance": "손해보험", "Publishing: Books/Magazines": "서적·잡지 출판", "Publishing: Newspapers": "신문", "Pulp & Paper": "펄프·제지",
  "Real Estate Development": "부동산 개발", "Real Estate Investment Trusts": "리츠", "Recreational Products": "레저 제품", "Regional Banks": "지방 은행",
  "Restaurants": "외식", "Savings Banks": "저축은행", "Semiconductors": "반도체", "Specialty Stores": "전문 소매", "Specialty Telecommunications": "특수 통신",
  "Steel": "철강", "Telecommunications Equipment": "통신 장비", "Textiles": "섬유", "Tobacco": "담배", "Tools & Hardware": "공구·하드웨어",
  "Trucking": "육상 운송", "Trucks/Construction/Farm Machinery": "건설·농업 기계", "Wholesale Distributors": "도매 유통", "Wireless Telecommunications": "무선 통신",
};
export const sectorLabel = (key: string) => LABELS[key] ?? key;
export const sectorIcon = (key: string) => (({ "Electronic Technology": "💠", "Finance": "🏦", "Health Technology": "💊", "Technology Services": "💻", "Producer Manufacturing": "⚙️", "Utilities": "⚡", "Consumer Durables": "🚘", "Transportation": "🚢", "Process Industries": "🧪", "Communications": "📡" } as Record<string, string>)[key] ?? "◈");
const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
export function sectorRankings(snapshot: SectorSnapshot, level: SectorLevel, period: SectorPeriod, board = ""): SectorRanking[] {
  const groups = new Map<string, SectorStock[]>();
  for (const stock of snapshot.stocks) {
    if (stock.date !== snapshot.date || stock.currency !== "KRW" || board && stock.exchange !== board) continue;
    // Include the parent to keep an identically named industry in different sectors separate.
    const key = level === "sector" ? stock.sector : `${stock.sector}\t${stock.industry}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(stock);
  }
  return [...groups].map(([key, members]) => {
    const available = members.map(stock => stock.returns[period]).filter(finite);
    const turnovers = members.map(stock => stock.turnover).filter(value => finite(value) && value >= 0) as number[];
    const caps = members.map(stock => stock.market_cap).filter(value => finite(value) && value > 0) as number[];
    const representative = [...members].sort((a, b) => (b.market_cap ?? -1) - (a.market_cap ?? -1) || (b.turnover ?? -1) - (a.turnover ?? -1) || a.ticker.localeCompare(b.ticker))[0];
    return { key, name: sectorLabel(level === "sector" ? members[0].sector : members[0].industry), sector: members[0].sector, members, representative,
      value: available.length ? available.reduce((a, b) => a + b, 0) / available.length : null, returnCount: available.length,
      turnover: turnovers.length ? turnovers.reduce((a, b) => a + b, 0) : null, turnoverCount: turnovers.length,
      marketCap: caps.length ? caps.reduce((a, b) => a + b, 0) : null, capCount: caps.length };
  });
}
export function sortSectors(rows: SectorRanking[], key: SectorSort, direction: "asc" | "desc") {
  const value = (row: SectorRanking) => key === "return" ? row.value : key === "count" ? row.members.length : row[key];
  return [...rows].sort((a, b) => {
    const x = value(a), y = value(b);
    if (x === null) return y === null ? a.name.localeCompare(b.name, "ko") : 1;
    if (y === null) return -1;
    return (x - y) * (direction === "desc" ? -1 : 1) || a.name.localeCompare(b.name, "ko");
  });
}
export function sectorMoney(value: number | null) {
  if (value === null) return "—";
  const unit = value >= 1e12 ? 1e12 : value >= 1e8 ? 1e8 : value >= 1e4 ? 1e4 : 1;
  return new Intl.NumberFormat("ko-KR", { maximumFractionDigits: unit === 1 ? 0 : 1 }).format(value / unit) + ({ [1e12]: "조원", [1e8]: "억원", [1e4]: "만원", 1: "원" }[unit]);
}
