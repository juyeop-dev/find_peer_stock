import { Link } from "react-router-dom";
import type { SemiconductorData } from "../dataClient/semiconductorTypes";

export function SemiconductorClassificationReview({ review }: { review: SemiconductorData["classification_review"] }) {
  if (!review) return null;
  return <details className="semiPanel semiClassificationReview">
    <summary>공정 분류 검토 · {review.reviewed_at}</summary>
    <p>{review.summary}</p>
    <p>사명 변경: {review.name_changes.map((change, index) => <span key={change.original}>
      {index > 0 && " · "}<Link to={`/semiconductors/${encodeURIComponent(change.ticker)}`}>{change.original} → {change.current}</Link>
    </span>)}</p>
    <ul>{review.exceptions.map((item) => <li key={item.original}>
      <strong>{item.original}</strong> ({item.image_role}): {item.note}
      {item.sources?.map((source) => <span key={source.url}> <a href={source.url} target="_blank" rel="noreferrer">{source.label} ↗</a></span>)}
    </li>)}</ul>
    {review.notes.map((note) => <p key={note}>{note}</p>)}
  </details>;
}
