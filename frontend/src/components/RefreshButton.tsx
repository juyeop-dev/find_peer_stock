import { LoadingSpinner } from "./LoadingSpinner";

interface RefreshButtonProps {
  loading: boolean;
  onClick: () => void;
}

export function RefreshButton({ loading, onClick }: RefreshButtonProps) {
  return (
    <button className="refreshButton" disabled={loading} type="button" onClick={onClick}>
      {loading ? <LoadingSpinner label="불러오는 중" /> : "최신 데이터 불러오기"}
    </button>
  );
}
