// 방문 통계(구글 애널리틱스 GA4). 화면 네 장(그래프·내 역사·방침·약관)과
// 서버가 그리는 /n/ 장이 **모두 이 파일 하나를 부른다** — 측정 ID 를 다섯
// 군데에 흩어 두면 그중 하나가 조용히 어긋난다 (광고 번호가 그렇게 네 곳에
// 박혀 있고, 바꿀 때마다 네 곳을 세어야 한다).
//
// **측정 ID 가 비어 있으면 아무것도 하지 않는다.** 아래 한 줄을 비우면 그
// 순간 꺼지고 요청 한 번 나가지 않는다 — 켜고 끄는 자리는 여기 하나다.
//
// **방침이 이 파일을 따라와야 한다.** 개인정보처리방침 제2조 4가 여기서 무엇을
// 보내는지 적고, 제4조가 그것이 구글(미국)로 가는 것을 국외 이전으로 적으며,
// 제6조·제7조가 쿠키와 거부 방법을 적는다 (제4판, 2026-09-09 공고·시행).
// 여기서 보내는 것을 늘리면 그 조문들도 같은 날 함께 고친다.
//
// 보내는 것은 GA4 가 기본으로 세는 것뿐이다 — 페이지가 열린 일. 어느 노드를
// 눌렀는지·검색창에 무엇을 쳤는지는 보내지 않는다 (그래프는 한 장 안에서
// 움직이므로 주소가 바뀌어도 저절로 세지 않는다). 여기에 무엇을 더하면 방침
// 제2조 4·제6조·제7조도 같이 고친다.
(function () {
  var ID = 'G-93TJVV76N0';
  if (!ID) return;

  window.dataLayer = window.dataLayer || [];
  window.gtag = function () { window.dataLayer.push(arguments); };
  window.gtag('js', new Date());
  window.gtag('config', ID);

  // 구글 쪽 스크립트는 여기서 부른다 — HTML 다섯 장에 <script> 를 두 줄씩
  // 두지 않기 위해서다. async 라 화면 그리기를 막지 않는다.
  var s = document.createElement('script');
  s.async = true;
  s.src = 'https://www.googletagmanager.com/gtag/js?id=' + encodeURIComponent(ID);
  document.head.appendChild(s);
})();
