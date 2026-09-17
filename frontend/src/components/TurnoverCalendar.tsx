import { useEffect, useRef } from "react";
import type { KeyboardEvent } from "react";
import "./NewHighCalendar.css";

interface Props {
  month: string;
  selectedDate: string;
  today: string;
  days: Record<string, number>;
  onMonthChange: (month: string) => void;
  onSelectDate: (date: string) => void;
}

const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];

function utcDate(year: number, monthIndex: number, day: number): Date {
  const value = new Date(0);
  value.setUTCFullYear(year, monthIndex, day);
  return value;
}

function dateKey(value: Date): string { return value.toISOString().slice(0, 10); }

export function TurnoverCalendar({ month, selectedDate, today, days, onMonthChange, onSelectDate }: Props) {
  const [year, monthNumber] = month.split("-").map(Number);
  const firstWeekday = utcDate(year, monthNumber - 1, 1).getUTCDay();
  const dayCount = utcDate(year, monthNumber, 0).getUTCDate();
  const cellCount = Math.ceil((firstWeekday + dayCount) / 7) * 7;
  const buttons = useRef(new Map<string, HTMLButtonElement>());
  const focusDate = useRef<string | null>(null);

  useEffect(() => {
    if (!focusDate.current) return;
    buttons.current.get(focusDate.current)?.focus();
    focusDate.current = null;
  }, [month, selectedDate]);

  function changeMonth(offset: number) {
    const next = utcDate(year, monthNumber - 1 + offset, 1);
    if (next.getUTCFullYear() >= 1 && next.getUTCFullYear() <= 9999) onMonthChange(dateKey(next).slice(0, 7));
  }

  function move(event: KeyboardEvent<HTMLButtonElement>, value: Date) {
    const offsets: Record<string, number> = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 };
    if (!(event.key in offsets)) return;
    event.preventDefault();
    const next = new Date(value);
    next.setUTCDate(next.getUTCDate() + offsets[event.key]);
    const key = dateKey(next);
    focusDate.current = key;
    if (key.slice(0, 7) !== month) onMonthChange(key.slice(0, 7));
    onSelectDate(key);
    buttons.current.get(key)?.focus();
  }

  return <section className="newHighCalendar turnoverCalendar" aria-label="거래대금 조회 날짜 선택">
    <div className="newHighCalendarTop">
      <span className="newHighCalendarTitle">날짜 선택</span>
      <button className="newHighCalendarTodayButton" type="button" onClick={() => {
        onMonthChange(today.slice(0, 7)); onSelectDate(today);
      }}>오늘</button>
    </div>
    <div className="newHighCalendarNavigation">
      <button type="button" onClick={() => changeMonth(-1)} aria-label="이전 달"><span aria-hidden="true">‹</span></button>
      <h2>{year}년 {monthNumber}월</h2>
      <button type="button" onClick={() => changeMonth(1)} aria-label="다음 달"><span aria-hidden="true">›</span></button>
    </div>
    <div className="newHighCalendarWeekdays" aria-hidden="true">
      {WEEKDAYS.map((day, index) => <span key={day} className={index === 0 ? "isSunday" : index === 6 ? "isSaturday" : undefined}>{day}</span>)}
    </div>
    <div className="newHighCalendarGrid">
      {Array.from({ length: cellCount }, (_, index) => {
        const day = index - firstWeekday + 1;
        if (day < 1 || day > dayCount) return <span className="newHighCalendarBlank" key={`blank-${index}`} />;
        const value = utcDate(year, monthNumber - 1, day);
        const key = dateKey(value);
        const count = days[key];
        const selected = key === selectedDate;
        const label = `${year}년 ${monthNumber}월 ${day}일, ${count === undefined ? "등록된 데이터 없음" : `거래대금 순위 ${count}종목`}`;
        return <button key={key} ref={(button) => {
          if (button) buttons.current.set(key, button);
          else buttons.current.delete(key);
        }}
          type="button" aria-label={label} aria-pressed={selected} aria-current={key === today ? "date" : undefined}
          className={["newHighCalendarDay", selected && "isSelected", key === today && "isToday",
            count !== undefined && "hasReport", index % 7 === 0 ? "isSunday" : index % 7 === 6 ? "isSaturday" : ""].filter(Boolean).join(" ")}
          onClick={() => onSelectDate(key)} onKeyDown={(event) => move(event, value)}>
          <span className="newHighCalendarDayNumber">{day}</span>
          <span className="newHighCalendarDayMeta">{count !== undefined ? <><i className="turnoverCalendarDot" />{count}</> : null}</span>
        </button>;
      })}
    </div>
    <div className="newHighCalendarLegend"><span><i className="turnoverCalendarDot" />거래대금 순위 등록</span></div>
    <p className="newHighCalendarHint">숫자는 등록된 상위 종목 수입니다.</p>
  </section>;
}
