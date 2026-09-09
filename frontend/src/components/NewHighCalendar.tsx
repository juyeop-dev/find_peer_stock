import { useEffect, useRef } from "react";
import type { KeyboardEvent } from "react";
import "./NewHighCalendar.css";

interface NewHighCalendarProps {
  month: string;
  selectedDate: string;
  today: string;
  days: Record<string, { total: number; high_52_week: number; high_all_time: number }>;
  onMonthChange: (month: string) => void;
  onSelectDate: (date: string) => void;
}

const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];

function utcDate(year: number, monthIndex: number, day: number): Date {
  const date = new Date(0);
  // Date.UTC treats years 0–99 as 1900–1999; setUTCFullYear preserves ISO years.
  date.setUTCFullYear(year, monthIndex, day);
  return date;
}

function inDateRange(date: Date): boolean {
  return date.getUTCFullYear() >= 1 && date.getUTCFullYear() <= 9999;
}

function dateKey(date: Date): string {
  return date.toISOString().slice(0, 10);
}

function fullDateLabel(date: Date): string {
  return `${date.getUTCFullYear()}년 ${date.getUTCMonth() + 1}월 ${date.getUTCDate()}일 ${WEEKDAYS[date.getUTCDay()]}요일`;
}

export function NewHighCalendar({
  month,
  selectedDate,
  today,
  days,
  onMonthChange,
  onSelectDate,
}: NewHighCalendarProps) {
  const [year, monthNumber] = month.split("-").map(Number);
  const firstWeekday = utcDate(year, monthNumber - 1, 1).getUTCDay();
  const dayCount = utcDate(year, monthNumber, 0).getUTCDate();
  const cellCount = Math.ceil((firstWeekday + dayCount) / 7) * 7;
  const dayButtons = useRef(new Map<string, HTMLButtonElement>());
  const focusDate = useRef<string | null>(null);

  useEffect(() => {
    if (focusDate.current) {
      const button = dayButtons.current.get(focusDate.current);
      if (button) {
        button.focus();
        focusDate.current = null;
      }
    }
  }, [month, selectedDate]);

  function changeMonth(offset: number) {
    const nextMonth = utcDate(year, monthNumber - 1 + offset, 1);
    if (inDateRange(nextMonth)) onMonthChange(dateKey(nextMonth).slice(0, 7));
  }

  function moveByKeyboard(event: KeyboardEvent<HTMLButtonElement>, date: Date) {
    const offsets: Record<string, number> = {
      ArrowLeft: -1,
      ArrowRight: 1,
      ArrowUp: -7,
      ArrowDown: 7,
      Home: -date.getUTCDay(),
      End: 6 - date.getUTCDay(),
    };
    if (!(event.key in offsets)) return;
    event.preventDefault();
    const nextDate = new Date(date);
    nextDate.setUTCDate(nextDate.getUTCDate() + offsets[event.key]);
    if (!inDateRange(nextDate)) return;
    const nextKey = dateKey(nextDate);
    focusDate.current = nextKey;
    if (nextKey.slice(0, 7) !== month) onMonthChange(nextKey.slice(0, 7));
    onSelectDate(nextKey);
    // Also handles Home/End on a day that is already selected.
    const nextButton = dayButtons.current.get(nextKey);
    if (nextButton) {
      nextButton.focus();
      focusDate.current = null;
    }
  }

  return (
    <section className="newHighCalendar" aria-label="신고가 조회 날짜 선택">
      <div className="newHighCalendarTop">
        <span className="newHighCalendarTitle">날짜 선택</span>
        <button
          className="newHighCalendarTodayButton"
          type="button"
          onClick={() => {
            onMonthChange(today.slice(0, 7));
            onSelectDate(today);
          }}
          aria-label="오늘 날짜 선택"
        >
          오늘
        </button>
      </div>
      <div className="newHighCalendarNavigation">
        <button type="button" onClick={() => changeMonth(-1)} aria-label="이전 달"
          disabled={year === 1 && monthNumber === 1}>
          <span aria-hidden="true">‹</span>
        </button>
        <h2 aria-live="polite" aria-atomic="true">{year}년 {monthNumber}월</h2>
        <button type="button" onClick={() => changeMonth(1)} aria-label="다음 달"
          disabled={year === 9999 && monthNumber === 12}>
          <span aria-hidden="true">›</span>
        </button>
      </div>
      <div className="newHighCalendarWeekdays" aria-hidden="true">
        {WEEKDAYS.map((weekday, index) => (
          <span key={weekday} className={index === 0 ? "isSunday" : index === 6 ? "isSaturday" : undefined}>
            {weekday}
          </span>
        ))}
      </div>
      <div className="newHighCalendarGrid">
        {Array.from({ length: cellCount }, (_, index) => {
          const day = index - firstWeekday + 1;
          if (day < 1 || day > dayCount) {
            return <span className="newHighCalendarBlank" key={`blank-${index}`} aria-hidden="true" />;
          }
          const date = utcDate(year, monthNumber - 1, day);
          const key = dateKey(date);
          const report = days[key];
          const selected = key === selectedDate;
          const isToday = key === today;
          const label = `${fullDateLabel(date)}, ${report
            ? `등록 ${report.total}종목, 52주 신고가 ${report.high_52_week}종목, 역대 신고가 ${report.high_all_time}종목`
            : "등록된 데이터 없음"}`;
          const classes = [
            "newHighCalendarDay",
            selected ? "isSelected" : "",
            isToday ? "isToday" : "",
            report ? "hasReport" : "",
            index % 7 === 0 ? "isSunday" : index % 7 === 6 ? "isSaturday" : "",
          ].filter(Boolean).join(" ");

          return (
            <button
              key={key}
              ref={(button) => {
                if (button) dayButtons.current.set(key, button);
                else dayButtons.current.delete(key);
              }}
              className={classes}
              type="button"
              aria-label={label}
              aria-pressed={selected}
              aria-current={isToday ? "date" : undefined}
              title={label}
              onClick={() => onSelectDate(key)}
              onKeyDown={(event) => moveByKeyboard(event, date)}
            >
              <span className="newHighCalendarDayNumber">{day}</span>
              <span className="newHighCalendarDayMeta" aria-hidden="true">
                {report ? (
                  report.total > 0 ? (
                    <>
                      <span className="newHighCalendarDots">
                        {report.high_52_week > 0 ? <i className="newHighCalendarDot is52Week" /> : null}
                        {report.high_all_time > 0 ? <i className="newHighCalendarDot isAllTime" /> : null}
                      </span>
                      <span>{report.total}</span>
                    </>
                  ) : <span className="newHighCalendarZero">등록 0</span>
                ) : null}
              </span>
            </button>
          );
        })}
      </div>
      <div className="newHighCalendarLegend">
        <span><i className="newHighCalendarDot is52Week" />52주 신고가</span>
        <span><i className="newHighCalendarDot isAllTime" />역대 신고가</span>
      </div>
      <p className="newHighCalendarHint">숫자는 등록된 종목 수입니다.</p>
    </section>
  );
}
