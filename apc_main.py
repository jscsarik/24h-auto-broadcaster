# -*- coding: utf-8 -*-
"""
========================================================================================
[동아방송예술대학교 졸업작품 / 캡스톤디자인]
프로젝트명: 메타데이터 기반 24시간 무인 자동 송출 시스템 (APC Prototype)
파일이름  : apc_main.py
역할 및 구성:
  1. CMS (Content Management System)  : 상대 경로 기반 영상 자산 스캔 및 영상 길이(Duration) 메타데이터 자동 추출
  2. DPC (Dynamic Playlist Controller): 방송 편성 규칙에 따른 실시간 무작위(Random) 큐시트 생성 엔진
  3. CDS (Content Delivery System)    : OBS Studio WebSocket(포트 6161)을 통한 미디어 소스 실시간 원격 제어
  4. APC (Automatic Program Control)  : 위 3대 시스템을 결합하여 24시간 끊김 없이 방송을 송출하는 마스터 루프
========================================================================================
[필수 라이브러리 설치]
  pip install obsws-python opencv-python

[OBS Studio 사전 세팅 안내]
  1. OBS 실행 후 상단 메뉴 [도구] -> [WebSocket 서버 설정] 클릭
  2. 'WebSocket 서버 활성화' 체크 확인 (설정 서버 포트: 6161)
  3. 비밀번호 설정 여부 확인 (비밀번호가 있다면 아래 OBS_CONFIG['password']에 입력)
  4. 대상 장면(기본 '장면 3')에 '미디어 소스' 2개를 추가하고 이름을 각각 'Player_1', 'Player_2'로 지정
========================================================================================
"""

import os
import sys
import time
import random
import logging
import datetime
from typing import Dict, List, Optional, Any

# obsws-python 라이브러리의 불필요한 내부 예외 로그(traceback) 억제
logging.getLogger("obsws_python").setLevel(logging.CRITICAL)

# Windows 콘솔 한글 인코딩 방어
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# OpenCV: 영상 메타데이터(FPS, Frame Count, Duration) 추출용
try:
    import cv2
except ImportError:
    print("[시스템 경고] 'opencv-python' 라이브러리가 설치되어 있지 않습니다.")
    print("터미널에 'pip install opencv-python'을 실행해 주세요.")
    sys.exit(1)

# obsws-python: OBS WebSocket v5 원격 제어용
try:
    import obsws_python as obs
except ImportError:
    print("[시스템 경고] 'obsws-python' 라이브러리가 설치되어 있지 않습니다.")
    print("터미널에 'pip install obsws-python'을 실행해 주세요.")
    sys.exit(1)


# ======================================================================================
# 0. 시스템 환경 설정 (CONFIGURATION)
# ======================================================================================
# 어디서 실행하든(USB, 다른 PC 등) 스크립트 위치를 기준으로 작동하는 기준 경로(상대 경로 기준점)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 영상 에셋 폴더 경로 매핑 (상대 경로로 자동 결합 -> 완벽한 이식성 보장)
FOLDER_CONFIG = {
    "MAIN": os.path.join(BASE_DIR, "본영상"),
    "AD": os.path.join(BASE_DIR, "광고 영상"),
    "LOGO": os.path.join(BASE_DIR, "로고 영상")
}

# 지원하는 비디오 포맷 확장자
SUPPORTED_EXTENSIONS = ('.mp4', '.mkv', '.mov', '.avi', '.ts', '.wmv')

# OBS Studio WebSocket 연결 설정
OBS_CONFIG = {
    "host": "localhost",
    "port": 6161,
    "password": "",               # OBS WebSocket 비밀번호 (설정되어 있다면 여기에 입력)
    "scene_name": "장면 3",       # 대상 장면 이름
    "players": ["Player_1", "Player_2"],  # 무중단 송출용 듀얼 미디어 플레이어 소스 이름
    "timeout": 5,                 # 연결 시도 타임아웃(초)
    "simulation_fallback": True   # OBS 미연결 시 테스트를 위해 가상 시뮬레이션 모드로 자동 전환 여부
}

# 방송국 송출 규칙 알고리즘 (큐 시퀀스)
# 규칙: [본영상 1개] -> [광고 영상 1번째] -> [광고 영상 2번째] -> [로고 영상 1개] -> 무한 반복
BROADCAST_SEQUENCE = ["MAIN", "AD", "AD", "LOGO"]


# ======================================================================================
# [CMS] Content Management System (콘텐츠 관리 시스템)
# ======================================================================================
class ContentManagementSystem:
    """
    [CMS 역할]
    방송국 자산 관리 시스템(MAM/CMS)의 축소판입니다.
    1. 지정된 저장소(본영상, 광고, 로고 폴더)를 상대 경로로 스캔합니다.
    2. OpenCV 백엔드를 활용하여 영상의 실제 재생 길이(Duration, 초), 해상도, FPS 등
       필수 메타데이터를 정밀하게 추출하고 인덱싱합니다.
    3. 필요 시 언제든 새로운 영상이 추가되어도 실시간으로 인식할 수 있도록 합니다.
    """

    def __init__(self, folder_config: Dict[str, str]):
        self.folder_config = folder_config
        self._ensure_directories()

    def _ensure_directories(self):
        """폴더가 존재하지 않는 경우 사용자에게 알리고 자동 생성 방어 로직을 수행합니다."""
        for category, folder_path in self.folder_config.items():
            if not os.path.exists(folder_path):
                try:
                    os.makedirs(folder_path, exist_ok=True)
                    print(f"[CMS 알림] 폴더가 존재하지 않아 자동 생성했습니다: {os.path.basename(folder_path)}")
                except Exception as e:
                    print(f"[CMS 오류] 폴더 생성 실패 ({folder_path}): {e}")

    def extract_video_metadata(self, file_path: str) -> Optional[Dict[str, Any]]:
        """
        OpenCV(cv2.VideoCapture)를 사용하여 영상 파일로부터 메타데이터를 추출합니다.
        
        반환값:
          - duration: 영상 재생 길이 (초 단위, float)
          - duration_str: 시:분:초 포맷 문자열 (HH:MM:SS)
          - fps: 초당 프레임 수
          - frame_count: 총 프레임 수
          - file_name: 파일명
          - absolute_path: OS 표준 절대 경로 (OBS 전달용)
        """
        if not os.path.exists(file_path):
            return None

        cap = cv2.VideoCapture(file_path)
        if not cap.isOpened():
            print(f"[CMS 경고] 비디오 파일을 열 수 없습니다: {file_path}")
            return None

        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()

        # 영상 길이(Duration) = 총 프레임 수 / FPS
        if fps > 0 and frame_count > 0:
            duration = frame_count / fps
        else:
            duration = 0.0

        # 시:분:초 포맷 변환
        duration_delta = datetime.timedelta(seconds=int(duration))
        duration_str = str(duration_delta)

        # OBS Studio 호환을 위해 슬래시(/) 형태의 절대 경로로 정규화
        normalized_abs_path = os.path.abspath(file_path).replace("\\", "/")

        return {
            "file_name": os.path.basename(file_path),
            "file_path": normalized_abs_path,
            "duration": round(duration, 2),
            "duration_str": duration_str,
            "fps": round(fps, 2),
            "frame_count": int(frame_count),
            "resolution": f"{width}x{height}",
            "file_size_mb": round(os.path.getsize(file_path) / (1024 * 1024), 2)
        }

    def scan_category(self, category: str) -> List[Dict[str, Any]]:
        """특정 카테고리(MAIN, AD, LOGO)의 모든 유효 영상 메타데이터 목록을 반환합니다."""
        folder_path = self.folder_config.get(category)
        if not folder_path or not os.path.exists(folder_path):
            return []

        media_list = []
        try:
            for item in os.listdir(folder_path):
                if item.lower().endswith(SUPPORTED_EXTENSIONS):
                    full_path = os.path.join(folder_path, item)
                    if os.path.isfile(full_path):
                        meta = self.extract_video_metadata(full_path)
                        if meta and meta["duration"] > 0:
                            meta["category"] = category
                            media_list.append(meta)
        except Exception as e:
            print(f"[CMS 오류] 폴더 스캔 중 오류 발생 ({folder_path}): {e}")

        return media_list


# ======================================================================================
# [DPC] Dynamic Playlist Controller (동적 편성 제어기)
# ======================================================================================
class DynamicPlaylistController:
    """
    [DPC 역할]
    고정된 시간표(Static Schedule) 대신 방송국의 비즈니스 룰에 따라
    실시간으로 다음 송출할 프로그램을 편성하고 큐시트를 생성합니다.
    - 전체 순서: [본영상 1개] -> [광고 영상 2개] -> [로고 영상 1개] (불변)
    - MAIN (본영상) : '라운드 로빈(Round-Robin) + 셔플' 방식
                      (모든 본영상이 1회씩 모두 방영되기 전까지 중복 송출 방지)
    - AD, LOGO     : 기존의 '단순 무작위(Random) + 직전 방영 중복 방지' 방식
    """

    def __init__(self, cms: ContentManagementSystem, sequence: List[str]):
        self.cms = cms
        self.sequence = sequence
        self.current_step_index = 0
        self.cycle_count = 1
        self.total_broadcast_count = 0
        self.last_played_by_category: Dict[str, str] = {}  # 카테고리별 직전 재생 파일 경로 캐시
        self.main_queue: List[Dict[str, Any]] = []          # MAIN(본영상) 전용 라운드로빈 셔플 큐

    def get_next_cue(self) -> Optional[Dict[str, Any]]:
        """
        송출 규칙 알고리즘에 따라 다음에 송출할 영상 메타데이터(Cue Item)를 선택합니다.
        1. MAIN (본영상): '라운드 로빈 + 셔플' + '실시간 JIT 유효성 검증'
           - 큐에서 꺼낸 파일이 디스크에 실존하는지 확인 (삭제된 파일 자동 스킵)
           - 파일이 덮어쓰기 되었을 경우에 대비해 최신 메타데이터(길이 등) 실시간 재추출
        2. AD / LOGO   : 매번 스캔 리스트에서 random.choice()로 무작위 선택.
           (직전 방영 영상과 연속 중복 방지 로직 유지)
        """
        target_category = self.sequence[self.current_step_index]
        selected_video: Optional[Dict[str, Any]] = None

        # =====================================================================
        # 1. MAIN (본영상) 선택 로직: '라운드 로빈 + 셔플' & 'JIT 유효성 검증'
        # =====================================================================
        if target_category == "MAIN":
            while not selected_video:
                # 큐가 비어있다면 본영상 폴더를 스캔하여 셔플 후 리필
                if not self.main_queue:
                    available_mains = self.cms.scan_category("MAIN")
                    if not available_mains:
                        print("[DPC 경고] '본영상' 폴더에 재생 가능한 영상이 없습니다!")
                        return None

                    # 리스트를 복사하여 무작위 셔플
                    shuffled_list = list(available_mains)
                    random.shuffle(shuffled_list)
                    self.main_queue = shuffled_list
                    print(f" >> [DPC 본영상 큐 리필] 총 {len(self.main_queue)}개 본영상 셔플 완료 (한 바퀴 돌 때까지 중복 없이 순차 송출)")

                # 큐에서 하나씩 꺼내서(pop) 검증 진행
                candidate_video = self.main_queue.pop()

                # [JIT 핵심 검증 1] 파일이 현재 디스크에 실제로 존재하는지 확인 (삭제 방어)
                if not os.path.exists(candidate_video["file_path"]):
                    print(f"[DPC 안내] 대기 중이던 '{candidate_video['file_name']}' 파일이 삭제되어 다음 영상으로 넘어갑니다.")
                    continue

                # [JIT 핵심 검증 2] 덮어쓰기(길이/스펙 변경)에 대비해 메타데이터 실시간 최신화
                updated_meta = self.cms.extract_video_metadata(candidate_video["file_path"])
                if updated_meta and updated_meta.get("duration", 0) > 0:
                    updated_meta["category"] = "MAIN"
                    selected_video = updated_meta
                else:
                    print(f"[DPC 안내] 대기 중이던 '{candidate_video['file_name']}' 영상 메타데이터 추출 실패로 다음 영상으로 넘어갑니다.")
                    continue

            # 최종 선택된 영상 경로 캐시 저장
            self.last_played_by_category["MAIN"] = selected_video["file_path"]

        # =====================================================================
        # 2. AD, LOGO (광고, 로고) 선택 로직: 기존 '단순 무작위(Random)' 유지
        # =====================================================================
        else:
            available_videos = self.cms.scan_category(target_category)
            if not available_videos:
                category_name_ko = {"AD": "광고 영상", "LOGO": "로고 영상"}.get(target_category, target_category)
                print(f"[DPC 경고] '{category_name_ko}' 폴더에 재생 가능한 영상이 없습니다!")
                return None

            # 직전 연속 송출 방지 로직 (후보 영상이 2개 이상일 때)
            candidates = available_videos
            last_played = self.last_played_by_category.get(target_category)
            if len(available_videos) > 1 and last_played:
                filtered = [v for v in available_videos if v["file_path"] != last_played]
                if filtered:
                    candidates = filtered

            selected_video = random.choice(candidates)
            self.last_played_by_category[target_category] = selected_video["file_path"]

        # 큐시트 관리 정보 부착
        self.total_broadcast_count += 1
        cue_info = {
            **selected_video,
            "cue_id": self.total_broadcast_count,
            "cycle": self.cycle_count,
            "step_index": self.current_step_index + 1,
            "total_steps": len(self.sequence),
            "category_code": target_category
        }

        # 다음 단계를 위해 인덱스 전이 (순환 루프)
        self.current_step_index += 1
        if self.current_step_index >= len(self.sequence):
            self.current_step_index = 0
            self.cycle_count += 1

        return cue_info


# ======================================================================================
# [CDS] Content Delivery System (OBS WebSocket 듀얼 플레이어 무중단 송출 제어기)
# ======================================================================================
class ContentDeliverySystem:
    """
    [CDS 역할]
    OBS Studio와 WebSocket(포트 6161) 프로토콜을 통해 통신하는 하드웨어/엔진 송출 제어기입니다.
    - 듀얼 플레이어(A/B Roll) 핑퐁 스위칭을 통해 단일 미디어 소스 교체 시 발생하는
      0.2초의 블랙아웃(암전)을 완벽히 제거합니다.
    - 물리적 디코딩 딜레이(0.15초)를 두고 가시성을 전환(True/False)하며,
      이전 플레이어에 즉시 STOP 액션을 전달하여 오디오 중첩을 방지합니다.
    """

    def __init__(self, host: str, port: int, password: str, scene_name: str, players: List[str]):
        self.host = host
        self.port = port
        self.password = password
        self.scene_name = scene_name
        self.players = players
        self.current_idx = 0
        self.item_ids: Dict[str, int] = {}
        self.client: Optional[obs.ReqClient] = None
        self.is_connected = False

    def connect(self) -> bool:
        """OBS WebSocket 서버에 연결을 수립하고 듀얼 플레이어의 Scene Item ID를 매핑합니다."""
        print(f"[CDS 통신] OBS WebSocket 연결 시도 중... ({self.host}:{self.port})")
        try:
            self.client = obs.ReqClient(
                host=self.host,
                port=self.port,
                password=self.password,
                timeout=OBS_CONFIG.get("timeout", 5)
            )
            # 연결 검증을 위해 OBS 버전 정보 요청
            version_info = self.client.get_version()
            obs_version = getattr(version_info, "obs_version", "알 수 없음")
            ws_version = getattr(version_info, "obs_web_socket_version", "5.x")
            print(f"[CDS 연결 성공] OBS Studio v{obs_version} (WebSocket v{ws_version})")
            self.is_connected = True

            # 듀얼 플레이어 고유 Scene Item ID 매핑
            self.item_ids = {}
            for player in self.players:
                try:
                    resp = self.client.get_scene_item_id(self.scene_name, player)
                    item_id = getattr(resp, "scene_item_id", getattr(resp, "sceneItemId", None))
                    if item_id is not None:
                        self.item_ids[player] = item_id
                        print(f"[CDS 매핑] '{self.scene_name}' 장면 내 '{player}' ID 매핑 성공 (ID: {item_id})")
                    else:
                        print(f"[CDS 주의] '{self.scene_name}' 장면에서 '{player}'의 ID를 가져오지 못했습니다.")
                except Exception as ex:
                    print(f"[CDS 경고] '{player}' ID 조회 중 오류 발생: {ex}")

            if len(self.item_ids) < len(self.players):
                print(f"[CDS 주의] OBS의 '{self.scene_name}' 장면에 {self.players} 소스가 모두 등록되어 있는지 확인해 주세요.")

            return True
        except Exception as e:
            print(f"[CDS 연결 실패] OBS WebSocket에 연결할 수 없습니다: {e}")
            print("  * 확인 사항:")
            print("    1. OBS Studio가 실행 중인지 확인해 주세요.")
            print(f"    2. [도구] -> [WebSocket 서버 설정]에서 '서버 활성화' 및 포트 {self.port} 확인")
            print("    3. 비밀번호가 설정되어 있다면 apc_main.py의 OBS_CONFIG['password']에 기재해 주세요.")
            self.is_connected = False
            self.client = None
            return False

    def switch_media_source(self, file_path: str) -> bool:
        """
        듀얼 플레이어(A/B Roll) 핑퐁 스위칭으로 블랙아웃과 오디오 겹침 없는 심리스(Seamless) 전환을 수행합니다.
        """
        if not self.is_connected or self.client is None:
            print("[CDS 경고] OBS 미연결 상태 - 재연결 시도 중...")
            if not self.connect():
                return False

        # 비상 정지(암전) 처리: 파일 경로가 비어있는 경우 모든 플레이어 정지 및 숨김
        if not file_path:
            try:
                for player in self.players:
                    p_id = self.item_ids.get(player)
                    if p_id is not None:
                        try:
                            self.client.set_scene_item_enabled(self.scene_name, p_id, False)
                        except Exception:
                            pass
                    try:
                        self.client.trigger_media_input_action(
                            name=player,
                            action="OBS_WEBSOCKET_MEDIA_INPUT_ACTION_STOP"
                        )
                    except Exception:
                        pass
                    try:
                        self.client.set_input_settings(name=player, settings={"local_file": ""}, overlay=True)
                    except Exception:
                        pass
                return True
            except Exception as e:
                print(f"[CDS 오류] 플레이어 초기화 실패: {e}")
                return False

        try:
            # a) current_idx를 바탕으로 current_player와 next_player 식별
            current_player = self.players[self.current_idx]
            next_idx = (self.current_idx + 1) % len(self.players)
            next_player = self.players[next_idx]

            # b) next_player에 set_input_settings로 file_path 세팅 및 RESTART 액션 트리거
            self.client.set_input_settings(
                name=next_player,
                settings={"local_file": file_path},
                overlay=True
            )
            try:
                self.client.trigger_media_input_action(
                    name=next_player,
                    action="OBS_WEBSOCKET_MEDIA_INPUT_ACTION_RESTART"
                )
            except Exception:
                pass

            # c) [핵심] 물리적 디코딩 딜레이 동안 정지 화면이 유지되도록 0.15초 대기
            time.sleep(0.15)

            # d) set_scene_item_enabled를 사용해 next_player 가시성 True, current_player 가시성 False 변경
            next_id = self.item_ids.get(next_player)
            curr_id = self.item_ids.get(current_player)

            if next_id is not None:
                try:
                    self.client.set_scene_item_enabled(self.scene_name, next_id, True)
                except Exception:
                    pass
            if curr_id is not None:
                try:
                    self.client.set_scene_item_enabled(self.scene_name, curr_id, False)
                except Exception:
                    pass

            # e) [오디오 겹침 방지 핵심] current_player가 백그라운드에서 재생되지 않도록 반드시 STOP 액션 트리거
            try:
                self.client.trigger_media_input_action(
                    name=current_player,
                    action="OBS_WEBSOCKET_MEDIA_INPUT_ACTION_STOP"
                )
            except Exception:
                pass

            # f) 인덱스(current_idx) 갱신
            self.current_idx = next_idx

            return True

        except Exception as e:
            print(f"[CDS 송출 오류] 듀얼 플레이어 스위칭 실패: {e}")
            self.is_connected = False
            return False


# ======================================================================================
# [APC] Automatic Program Controller (주조정실 자동 송출 관제 시스템)
# ======================================================================================
class AutomaticProgramController:
    """
    [APC 마스터 관제탑]
    CMS(자산/메타데이터), DPC(동적 편성), CDS(OBS 원격 제어)를 하나로 묶어
    24시간 365일 무인으로 정밀하게 영상을 스위칭 및 송출하는 메인 관제 루프입니다.
    """

    def __init__(self):
        self.cms = ContentManagementSystem(FOLDER_CONFIG)
        self.dpc = DynamicPlaylistController(self.cms, BROADCAST_SEQUENCE)
        self.cds = ContentDeliverySystem(
            host=OBS_CONFIG["host"],
            port=OBS_CONFIG["port"],
            password=OBS_CONFIG["password"],
            scene_name=OBS_CONFIG["scene_name"],
            players=OBS_CONFIG["players"]
        )

    def display_header(self):
        """방송국 주조정실 콘솔 배너를 출력합니다."""
        print("=" * 80)
        print("      [DIMA BROADCASTING APC] 24시간 무인 자동 송출 관제 시스템 v1.0")
        print("          - CMS (Content Management System) : 메타데이터 자동 추출")
        print("          - DPC (Dynamic Playlist Controller) : 실시간 랜덤 큐시트 편성")
        print("          - CDS (Content Delivery System)   : OBS Studio 듀얼 플레이어 무중단 스위칭")
        print("=" * 80)
        print(f" * 기준 작업 경로 : {BASE_DIR}")
        print(f" * 송출 규칙 순서 : {' -> '.join(BROADCAST_SEQUENCE)}")
        print(f" * OBS 대상 장면 : {OBS_CONFIG['scene_name']} (Port: {OBS_CONFIG['port']})")
        print(f" * 듀얼 플레이어 : {', '.join(OBS_CONFIG['players'])}")
        print("=" * 80 + "\n")

    def run(self):
        """APC 24시간 무인 송출 메인 루프를 가동합니다."""
        self.display_header()

        # 1. OBS WebSocket 연결 시도
        obs_online = self.cds.connect()
        if not obs_online:
            print("\n" + "!" * 80)
            print(" [안내] OBS에 연결되지 않았습니다.")
            print("        OBS를 켜지 않아도 '가상 시뮬레이션 모드'로 송출 알고리즘 동작을 확인할 수 있습니다.")
            print("!" * 80)

        print("\n[APC 가동] 24시간 무인 자동 송출 관제를 시작합니다. (중단하려면 Ctrl+C를 누르세요)\n")

        try:
            while True:
                # -------------------------------------------------------------
                # STEP 1: [DPC] 송출 규칙에 따른 실시간 큐시트 생성 및 메타데이터 획득
                # -------------------------------------------------------------
                cue = self.dpc.get_next_cue()
                if not cue:
                    print("[APC 대기] 송출 가능한 영상이 없습니다. 5초 후 재시도합니다...")
                    time.sleep(5)
                    continue

                category_labels = {
                    "MAIN": "[본방송 ON-AIR]",
                    "AD":   "[광고 송출 AD]",
                    "LOGO": "[스테이션 ID/로고]"
                }
                cat_label = category_labels.get(cue['category_code'], f"[{cue['category_code']}]")

                now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                print("-" * 80)
                print(f" [{now_str}] CUE #{cue['cue_id']:04d} | 사이클 {cue['cycle']}회차 ({cue['step_index']}/{cue['total_steps']})")
                print(f" 구분       : {cat_label}")
                print(f" 영상 파일  : {cue['file_name']}")
                print(f" 재생 길이  : {cue['duration_str']} ({cue['duration']:.2f}초)")
                print(f" 메타데이터 : {cue['resolution']} | {cue['fps']} FPS | {cue['file_size_mb']} MB")
                print("-" * 80)

                # -------------------------------------------------------------
                # STEP 2: [CDS] OBS WebSocket으로 미디어 소스 교체 및 송출 실행
                # -------------------------------------------------------------
                if self.cds.is_connected:
                    success = self.cds.switch_media_source(cue['file_path'])
                    if success:
                        active_player = self.cds.players[self.cds.current_idx]
                        print(f" >> [CDS ON-AIR] OBS 듀얼 플레이어 전환 성공 -> [{active_player}] '{cue['file_name']}' 송출 시작")
                    else:
                        print(f" >> [CDS 오류] OBS 미디어 소스 전환 실패")
                else:
                    print(f" >> [시뮬레이션 모드] 가상 송출 진행 중 (OBS 미연결)")

                # -------------------------------------------------------------
                # STEP 3: 영상 길이(Duration)만큼 정밀 대기 후 다음 순서로 전이
                # (영상 끝부분 잘림 방지를 위해 remaining = duration + 0.5초 버퍼 적용)
                # -------------------------------------------------------------
                duration = cue['duration']
                remaining = duration + 0.5
                print(f" >> [송출 카운트다운] 총 {remaining:.1f}초 (영상 {duration:.1f}초 + 버퍼 0.5초) 동안 재생 대기 중...")

                while remaining > 0:
                    sleep_chunk = min(1.0, remaining)
                    time.sleep(sleep_chunk)
                    remaining -= sleep_chunk

                    # 10초 간격 또는 마지막 5초 카운트다운 표시
                    rem_int = int(remaining)
                    if rem_int > 0 and (rem_int % 10 == 0 or remaining <= 5):
                        print(f"    ... [ON-AIR 진행 중] 잔여 시간: {remaining:5.1f}초 / {duration + 0.5:.1f}초", end="\r")

                print(f"\n >> [CUE 완료] CUE #{cue['cue_id']:04d} 송출 완료. 즉시 다음 편성으로 전환합니다.\n")

        except KeyboardInterrupt:
            print("\n\n" + "=" * 80)
            print("[APC 비상 정지] 사용자에 의해 송출 관제 시스템 종료 절차가 시작되었습니다.")

            # OBS 연결 상태인 경우 미디어 소스를 빈 경로로 교체하여 재생 강제 종료 (화면 암전 처리)
            if self.cds.is_connected:
                if self.cds.switch_media_source(""):
                    print(" >> [CDS 초기화] OBS 미디어 소스를 비우고 송출 화면을 닫았습니다.")

            print("[APC 종료 완료] 송출 관제 시스템이 안전하게 종료되었습니다.")
            print("=" * 80)


# ======================================================================================
# 메인 진입점 (Entry Point)
# ======================================================================================
if __name__ == "__main__":
    apc = AutomaticProgramController()
    apc.run()
