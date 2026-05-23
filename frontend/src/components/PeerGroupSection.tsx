import { Link } from "react-router-dom";
import { getExternalQuoteLink } from "../dataClient/externalLinks";
import { changeTone, formatChange, formatDateTime, formatPrice } from "../dataClient/formatters";
import type { PeerGroup } from "../dataClient/types";

interface PeerGroupSectionProps {
  group: PeerGroup;
}

export function PeerGroupSection({ group }: PeerGroupSectionProps) {
  return (
    <section className="peerSection">
      <div className="sectionTitle">
        <h2>
          <span aria-hidden="true">{group.group.emoji}</span>
          {group.group.name}
        </h2>
        {group.group.summary ? <span>{group.group.summary}</span> : null}
      </div>
      <div className="tableWrap">
        <table className="peerTable">
          <thead>
            <tr>
              <th>기업</th>
              <th>국가</th>
              <th>사업 메모</th>
              <th>현재가</th>
              <th>전일 대비</th>
              <th>조회 시각</th>
              <th>출처</th>
            </tr>
          </thead>
          <tbody>
            {group.peers.map((peer) => {
              const tone = changeTone(peer.quote);
              const externalQuoteLink = getExternalQuoteLink(peer.company.ticker);
              return (
                <tr key={peer.company.ticker}>
                  <td>
                    <Link className="companyLink" to={`/stocks/${encodeURIComponent(peer.company.ticker)}`}>
                      {peer.company.name_kr}
                    </Link>
                    <a
                      className="tickerText tickerExternalLink"
                      href={externalQuoteLink.href}
                      target="_blank"
                      rel="noreferrer"
                      title={`${peer.company.ticker} external quote (${externalQuoteLink.label})`}
                      aria-label={`${peer.company.ticker} external quote (${externalQuoteLink.label})`}
                    >
                      {peer.company.ticker}
                    </a>
                  </td>
                  <td>{peer.company.country}</td>
                  <td>{peer.company.note || peer.company.sector || "-"}</td>
                  <td>{formatPrice(peer.quote)}</td>
                  <td className={tone}>{formatChange(peer.quote)}</td>
                  <td>{formatDateTime(peer.quote.fetched_at)}</td>
                  <td>{peer.quote.source}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
