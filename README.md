# 수저맵

내 예산(흙수저 1만 원 · 은수저 1.5만 원 · 금수저 2만 원 · 다이아수저 3만 원)에 맞는 메뉴를 지도에서 찾는 서비스예요.

- 지도: MapLibre + OpenFreeMap (키 필요 없음, OpenStreetMap 기반)
- 가게·메뉴: 행정안전부 착한가격업소 공공데이터
- 주소 → 좌표: 도로명주소 검색 API + 좌표제공 검색 API (business.juso.go.kr)

## 폴더 구조

```
index.html                     화면 (GitHub Pages로 공개)
assets/                        로고, 수저 캐릭터 이미지
data/raw/                      ← 착한가격업소 CSV를 여기에 올려요
data/kr.json                   지도에 쓰는 데이터 (자동 생성)
data/kr_report.json            처리 결과 요약 (자동 생성)
data/cache/geocode.json        찾은 주소·좌표 저장 (자동 생성, 다음 실행 때 재사용)
scripts/build_kr.py            데이터 만드는 스크립트
.github/workflows/build-kr.yml GitHub에서 스크립트를 실행하는 설정
```

## 처음 한 번 설정

1. **Secrets 등록**: 저장소 Settings → Secrets and variables → Actions → New repository secret
   - `JUSO_SEARCH_KEY` : 도로명주소 **검색 API** 승인키
   - `JUSO_COORD_KEY` : **좌표제공** 검색 API 승인키 (승인 나면 등록. 없어도 1단계는 돌아가요)
2. **CSV 올리기**: data.go.kr/data/3045247 에서 받은 파일을 `data/raw/` 에 올려요. 파일 이름은 그대로 두세요 (기준일을 이름에서 읽어요).
3. **Actions 권한 확인**: Settings → Actions → General → Workflow permissions → **Read and write permissions** 선택 → Save
4. **사이트 공개**: Settings → Pages → Source: Deploy from a branch → Branch: `main`, 폴더 `/ (root)` → Save
   - 몇 분 뒤 https://noseed-star.github.io/sujeomap 에서 열려요

## 데이터 만들기

Actions 탭 → 왼쪽 **build-kr** → **Run workflow**

- `sido`: 처리할 시도. 처음엔 `서울특별시`로 시작하고, 잘 되면 `전국`
- `limit`: 시험 삼아 조금만 돌리고 싶으면 숫자 (예: 50). 0이면 전부

실행이 끝나면 `data/kr.json` 이 자동으로 저장(커밋)되고, 사이트에 반영돼요.

- 좌표 키가 없을 때: 주소 코드 찾기까지만 하고 끝나요. 좌표 키를 등록한 뒤 다시 실행하면 이미 찾은 주소는 건너뛰고 좌표만 붙여요.
- 결과 확인: Actions 실행 화면의 '한국 데이터 만들기' 로그 마지막 부분, 또는 `data/kr_report.json`

## 분기마다 할 일

1. 새 착한가격업소 CSV를 `data/raw/` 에 올리고, 예전 CSV는 지워요 (가장 최근 파일 하나만 읽어요)
2. build-kr 를 `전국` 으로 실행

## 해외 접속이 막힐 때 (PC에서 실행하기)

GitHub Actions 서버는 해외에 있어서 도로명주소 API가 연결을 막을 수 있어요. 로그에 "서버에 연결하지 못했어요"가 나오면 PC에서 실행하세요.

```bash
# 저장소를 내 PC로 받기 (GitHub Desktop을 써도 돼요)
git clone https://github.com/noseed-star/sujeomap.git
cd sujeomap
pip install -r requirements.txt

# Windows PowerShell
$env:JUSO_SEARCH_KEY="검색API키"; $env:JUSO_COORD_KEY="좌표API키"; $env:SIDO="서울특별시"
python scripts/build_kr.py

# 결과 올리기
git add data
git commit -m "data: 한국 데이터 갱신"
git push
```

## 알아둘 점

- 가격은 공공데이터 기준일 기준이라 실제와 다를 수 있어요. 화면에 출처와 기준일을 표시해요.
- 출석·리뷰·캐릭터 꾸미기 기록은 지금은 이용자 기기(브라우저)에만 저장돼요.
- 지도 출처 표기(OpenStreetMap, OpenFreeMap)는 지우지 마세요.
