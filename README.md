# 24h-auto-broadcaster
파이썬과 OBS WebSocket을 이용한 24시간 무인 송출 시스템. (동방예대 캡스톤 프로젝트)

## 개요
비싼 방송용 스위처 장비 없이 PC 한 대로 24시간 영상 뺑뺑이 돌리는 자동화 스크립트. 

## 주요 특징
* **무중단 핫스왑 (Hot-Swapping)**
  * 송출 중에 영상 폴더 건드려도 시스템 안 뻗음. 영상 파일 넣거나 빼면 알아서 감지해서 다음 큐시트에 바로 반영됨. 재부팅 필요 없음.
* **A/B Roll 스위칭 (블랙 화면 방지)**
  * OBS에서 미디어 소스 하나만 쓰면 영상 넘어갈 때 디코딩 딜레이 때문에 까맣게 깜빡거림. 이거 보기 싫어서 듀얼 플레이어로 짰음.
  * 뒤에서 0.15초 미리 버퍼링 걸어두고 소스 가시성 껐다 켜는 방식이라 화면 끊김 없음.
* **러닝타임 자동 계산**
  * OpenCV로 프레임이랑 FPS 긁어와서 영상 길이 밀리초 단위로 알아서 계산함.

## Tech Stack
* Python 3
* `opencv-python`, `obs-websocket-py`
* OBS Studio

## 구조 및 시연
<!-- 여기에 시스템 구조도(pdf 캡처본) 드래그 앤 드롭 -->
<img width="400" height="260" alt="image" src="https://github.com/user-attachments/assets/f7b1bb6d-e97f-46ac-ac4e-2b14a28f0e70" />
<img width="400" height="260" alt="image" src="https://github.com/user-attachments/assets/1944eb8d-e679-4a37-91e4-076b36ae9272" />
<img width="380" height="230" alt="image" src="https://github.com/user-attachments/assets/db4c1b57-500f-4a3c-b792-ec5deba9c61f" />


<!-- 터미널 돌아가는 거랑 OBS 화면 넘어가는 거 짧은 GIF로 따서 올리면 좋음 -->
<img width="540" height="288" alt="Animation112_2" src="https://github.com/user-attachments/assets/6d96ea53-c34f-4735-9f92-837639e79266" />



https://www.youtube.com/watch?v=8eyowboviXM
