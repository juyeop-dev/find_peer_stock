# TradingView 공식 차트 UI

사용자가 TradingView에서 제공하는 실제 차트 UI 전체를 확인하고 적용하도록 요청했다.

공식 Advanced Chart 위젯을 공통 종목 차트에 연결했다. 지원 종목은 TradingView 탭이 기본이며, 이전에 직접 만든 종가·비교·채널·기준점 측정과 저장된 선은 ‘저장 일봉·분석’ 탭에 보존한다. 탭 전환과 시세 갱신으로 공식 위젯 인스턴스를 다시 만들지 않는다.

## 확인 및 적용한 메뉴

- 상단: 심볼 검색과 비교, 분·시간·일 간격, 캔들·봉·영역 등 차트 종류, 지표, 팝업, 이미지 저장.
- 좌측: 커서·추세선·레이·수평선·수직선·평행/회귀 채널·피치포크, 갠·피보나치, 패턴, 예측·측정, 도형·브러시, 텍스트·주석, 아이콘, 자석, 확대.
- 차트: 확대·이동, 날짜 범위, 자동·로그 가격 축, 거래량.
- 우측: 관심 목록, 현재 선택 종목 상세, 핫리스트.
- 사이트: 크게 보기, 정확한 거래소 심볼로 TradingView 전체 기능 열기, 외부 스크립트 실패 안내·재시도와 저장 차트 전환.

위젯을 실제로 로드한 브라우저에서 도구 그룹 16개의 존재와 추세/채널·피보나치·봉 종류·비교·지표 메뉴를 확인했다. 과거 코드의 `hide_side_toolbar: true`, `allow_symbol_change: false`를 해제했다. 한국어 UI와 제공처의 실제 캔들·거래량 데이터를 사용하며 종가에서 OHLC를 만들어 넣지 않는다. 로고와 출처 표기를 유지한다.

## 공식 제공 범위와 실제 제한

- KRX: SK하이닉스의 실제 위젯에서 ‘TradingView에서만 제공되는 심볼’ 응답을 확인했다. 한국 종목을 다른 시장의 대체 심볼로 바꾸지 않는다. KRX는 사용 가능한 저장 차트를 기본으로 두고, 모든 탭에서 동일한 `KRX:종목코드`의 TradingView 전체 화면을 바로 열 수 있게 했다. 공식 탭에서도 제한 이유와 직접 열기 동작을 보여준다.
- 위젯은 TradingView 데이터를 사용하며 사이트의 자체 데이터를 주입하는 API를 제공하지 않는다. 기존 2019년 이후 수집 이력은 저장 분석 탭에 계속 남긴다.
- TradingView.com의 Pine Script·알림·전략 테스트·계정 저장 기능까지 외부 위젯에 복제하지 않는다. 동일 종목의 원본 전체 화면으로 연결한다. 별도 허가가 필요한 Advanced Charts/Trading Platform 라이브러리를 공개 저장소에 가져오지 않았다.

## 공식 확인 자료

- [기술 분석 위젯 예제](https://www.tradingview.com/widget-docs/widgets/charts/advanced-chart/demos/technical-analysis/)
- [관심 목록 예제](https://www.tradingview.com/widget-docs/widgets/charts/advanced-chart/demos/watchlist/)
- [종목 상세·핫리스트 예제](https://www.tradingview.com/widget-docs/widgets/charts/advanced-chart/demos/analytics-platform/)
- [데이터 제한과 자체 데이터 연결 범위](https://www.tradingview.com/widget-docs/faq/data/)
- [전체 사이트와 라이브러리의 기능 차이](https://www.tradingview.com/charting-library-docs/latest/resources/Frequently-Asked-Questions/)
- [라이브러리 공식 배포·접근 범위](https://www.tradingview.com/charting-library-docs/latest/quick-start/)

타입 검사와 프런트엔드 51개 테스트, 공식 위젯의 실제 메뉴·모바일·KRX 제한·스크립트 실패/재시도, 기존 저장 차트의 채널·기준점·비교 회귀 검사 및 툴팁 36건을 통과했다. 운영 배포 결과는 완료 후 기록한다.
