interface LoadingSpinnerProps {
  label?: string;
}

export function LoadingSpinner({ label = "불러오는 중" }: LoadingSpinnerProps) {
  return (
    <span className="spinnerLabel" role="status">
      <span className="spinner" aria-hidden="true" />
      {label}
    </span>
  );
}
