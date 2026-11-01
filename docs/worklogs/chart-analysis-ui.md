# 그리기·분석 도구 UI (2026-11-01 KST)

종목 상세의 **그리기·분석** 탭에 도구 모음과 지표 선택창을 추가했습니다. 기존에는 기본 선 도구만 있고 TradingView 공식 위젯이 별도 탭에 있어 요청한 기능을 이 탭에서 사용할 수 없었습니다.

## 추가한 기능

- 왼쪽 도구 모음: 이동, 추세선, 레이, 화살표, 수평선, 수직선, 평행 채널, 피보나치 되돌림, 사각형, 기간·가격 측정. 모바일은 2행으로 표시합니다.
- 채널은 두 점으로 만들고 기존 평행선·중간선·간격 조절과 끝점 편집을 사용합니다. 피보나치는 0/23.6/38.2/50/61.8/78.6/100% 수준을 표시합니다.
- 상단 **지표** 창: MA 20/60/120, EMA 20/60, 볼린저 밴드 20·2, RSI 14, MACD 12·26·9. 지표 검색과 전체 제거를 지원합니다. 가격 지표는 차트 위에, RSI·MACD는 날짜 범위를 공유하는 보조 패널에 표시합니다.
- 선/영역 차트, 격자 설정, 새 그리기의 선 두께·점선, 객체 목록·개별 숨김·잠금·삭제, 전체 그리기 숨김, 실행 취소·다시 실행, 보조 패널을 포함한 PNG 저장을 제공합니다.
- 지표·표시 설정과 그리기는 브라우저에 종목별로 보존합니다. 기존 저장 그리기와 비교 기준별 분리를 유지합니다. 잠긴 객체는 드래그로 이동하거나 끝점을 바꿀 수 없습니다.
- Alt+T/H/V/F/R/C/M으로 도구를 선택합니다. Esc는 도구·대화상자를 닫으며, 지표·설정창을 닫아도 확대 화면은 유지됩니다.

## 계산과 제공 범위

확인된 실제 일별 종가를 사용합니다. 부분 준비 기간에 지표를 만들지 않으며 선택 기간 이전의 저장 이력도 계산에 사용합니다. EMA는 완전한 SMA로 초기화하고 이후 `2/(N+1)`로 평활합니다. 볼린저는 모집단 표준편차, RSI는 Wilder 평활, MACD는 12/26 EMA 차이와 9 EMA 시그널입니다. 수익률 비교 중 가격 지표는 숨기고 RSI·MACD는 기본 종목 기준으로 유지합니다. 제공하지 않는 OHLC·거래량이나 휴장일 가격을 생성하지 않습니다.

이는 사이트의 데이터와 그리기 엔진으로 구현한 기능입니다. TradingView 공식 전체 라이브러리를 설치한 것으로 표시하지 않습니다. 공식 Advanced Charts는 별도 접근·사용 승인이 필요한 제품이며 Pine·서버 알림·전략 테스터는 이번 범위에 포함하지 않습니다. 기존 공식 위젯 탭과 출처 표시는 유지합니다.

참고: [TradingView 라이브러리 안내](https://www.tradingview.com/free-charting-libraries/), [RSI](https://www.tradingview.com/support/solutions/43000502338-relative-strength-index-rsi/), [MACD](https://www.tradingview.com/support/solutions/43000502344-moving-average-convergence-divergence-macd-indicator/).

## 검증

```powershell
node node_modules/typescript/bin/tsc -b
npm.cmd run test:stock-history
npm.cmd run test:chart-analysis
npm.cmd run test:chart-analysis:browser
npm.cmd run test:chart-workspace:browser
npm.cmd run test:chart-replay:browser
```

계산 테스트는 RSI의 독립 기준값, 선형 가격에서의 MACD 기준값, EMA/밴드 초기 구간, 미래 자료 추가 시 과거 값 불변, 피보나치 방향과 설정 검증을 포함합니다. 브라우저 테스트는 10개 도구 표시와 새 도구 그리기, 채널·피보나치, 객체 잠금·숨김, 저장 복원, 지표, PNG, 대화상자와 확대 화면, 1440/390/320px를 확인합니다. 화면과 PNG는 `data/tmp_chart_analysis/ui/`에 기록합니다.
