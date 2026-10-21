import type { SectorCalendarRecord } from "../dataClient/sectorRankings";

interface Props {
  month: string; selectedDate: string; latestDate: string; records: SectorCalendarRecord[];
  onMonthChange: (month: string) => void; onSelectDate: (date: string) => void; onLatest: () => void;
}
const weekdays = ["일", "월", "화", "수", "목", "금", "토"];
export function SectorCalendar({ month, selectedDate, latestDate, records, onMonthChange, onSelectDate, onLatest }: Props) {
  const [year, number] = month.split("-").map(Number);
  const first = new Date(Date.UTC(year, number - 1, 1)).getUTCDay();
  const count = new Date(Date.UTC(year, number, 0)).getUTCDate();
  const byDate = new Map(records.map(record => [record.date, record]));
  const months = records.map(record => record.date.slice(0, 7)).sort();
  const minimum = months[0] ?? month, maximum = months.at(-1) ?? month;
  function move(offset: number) { onMonthChange(new Date(Date.UTC(year, number - 1 + offset, 1)).toISOString().slice(0, 7)); }
  return <section className="semiPanel sectorCalendar" aria-label="섹터 조회 날짜 선택">
    <div className="sectorCalendarHeading"><div><h2>섹터 캘린더</h2><p>기록이 있는 날짜를 선택하면 당시 순위와 구성 종목을 볼 수 있습니다.</p></div><button type="button" className="semiTextButton" onClick={onLatest}>최신 기록</button></div>
    <div className="sectorCalendarNavigation"><button type="button" aria-label="이전 달" disabled={month <= minimum} onClick={() => move(-1)}>‹</button><label><span className="sectorSrOnly">조회 월</span><input type="month" value={month} min={minimum} max={maximum} onChange={event => { if (/^\d{4}-(0[1-9]|1[0-2])$/.test(event.target.value) && event.target.value >= minimum && event.target.value <= maximum) onMonthChange(event.target.value); }} /></label><button type="button" aria-label="다음 달" disabled={month >= maximum} onClick={() => move(1)}>›</button></div>
    <div className="sectorCalendarGrid" aria-hidden="true">{weekdays.map(day => <span className="sectorCalendarWeekday" key={day}>{day}</span>)}</div>
    <div className="sectorCalendarGrid">{Array.from({ length: Math.ceil((first + count) / 7) * 7 }, (_, index) => {
      const day = index - first + 1;
      if (day < 1 || day > count) return <span key={index} />;
      const date = `${month}-${String(day).padStart(2, "0")}`;
      const record = byDate.get(date);
      return <button type="button" key={date} data-date={date} disabled={!record} aria-label={`${year}년 ${number}월 ${day}일, ${record ? `${record.industries}개 업종, ${record.count}개 종목 기록` : "저장된 기록 없음"}`} aria-pressed={date === selectedDate} aria-current={date === latestDate ? "date" : undefined} onClick={() => onSelectDate(date)}><strong>{day}</strong><span>{record ? "저장" : "미기록"}</span></button>;
    })}</div>
    <p className="semiFootnote">저장된 실제 스냅샷만 제공하며 기록이 없는 날짜는 선택할 수 없습니다.</p>
  </section>;
}
