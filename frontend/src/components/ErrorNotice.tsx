interface ErrorNoticeProps {
  title?: string;
  message: string;
}

export function ErrorNotice({ title = "데이터 오류", message }: ErrorNoticeProps) {
  return (
    <div className="notice errorNotice">
      <strong>{title}</strong>
      <span>{message}</span>
    </div>
  );
}
