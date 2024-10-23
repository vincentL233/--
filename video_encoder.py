import subprocess
import os
import sys
from typing import Optional, Dict, Tuple, List
from dataclasses import dataclass
from pathlib import Path
import logging
import shutil

@dataclass
class VideoInfo:
    """視訊檔案資訊的資料類別"""
    video_stream: str = ""
    duration: str = ""
    file_size: float = 0.0  # MB
    width: int = 0
    height: int = 0
    fps: float = 0.0
    bitrate: str = ""

class FFmpegNotFoundError(Exception):
    """FFmpeg 未找到時的自訂例外"""
    pass

class VVCNotSupportedError(Exception):
    """不支援 H.266/VVC 編碼時的自訂例外"""
    pass

class VideoEncoder:
    """視訊編碼器類別"""
    
    VALID_PRESETS = ["faster", "fast", "medium", "slow", "slower"]
    
    def __init__(self, ffmpeg_path: Optional[str] = None):
        self.ffmpeg_path = ffmpeg_path or self._find_ffmpeg()
        self._setup_logging()
        self._verify_vvc_support()
    
    def _setup_logging(self) -> None:
        """設定日誌記錄"""
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        
        log_file = log_dir / f"video_encoder_{os.getpid()}.log"
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler(log_file, encoding='utf-8')
            ]
        )
        self.logger = logging.getLogger(__name__)

    def _find_ffmpeg(self) -> str:
        """尋找 FFmpeg 執行檔"""
        try:
            # Windows 系統使用 where 命令
            if os.name == 'nt':
                process = subprocess.run(
                    ["where", "ffmpeg"],
                    capture_output=True,
                    text=True,
                    check=True
                )
                paths = process.stdout.strip().split('\n')
            # Unix-like 系統使用 which 命令
            else:
                process = subprocess.run(
                    ["which", "ffmpeg"],
                    capture_output=True,
                    text=True,
                    check=True
                )
                paths = [process.stdout.strip()]

            for path in paths:
                path = path.strip()
                if path and os.path.exists(path):
                    return path

        except subprocess.CalledProcessError:
            # 如果 where/which 命令失敗，嘗試搜尋常見路徑
            pass

        # 檢查常見路徑
        common_paths = [
            # 添加用戶實際的安裝路徑
            Path(r"C:\ffmpe\ffmpeg-2024-10-21-git-baa23e40c1-full_build\bin\ffmpeg.exe"),
            # 保留其他可能的路徑
            Path(r"C:\ffmpeg\ffmpeg-master-latest-win64-gpl\bin\ffmpeg.exe"),
            Path(r"C:\ffmpeg\bin\ffmpeg.exe"),
            Path(r"C:\Program Files\ffmpeg\bin\ffmpeg.exe"),
            Path(r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe"),
            Path.cwd() / "ffmpeg.exe",
            Path("/usr/bin/ffmpeg"),
            Path("/usr/local/bin/ffmpeg")
        ]
        
        # 從環境變數 PATH 中的所有目錄尋找 ffmpeg.exe
        if os.name == 'nt':
            path_dirs = os.environ.get('PATH', '').split(os.pathsep)
            for dir_path in path_dirs:
                try:
                    ffmpeg_path = Path(dir_path.strip('"')) / "ffmpeg.exe"
                    if ffmpeg_path.exists():
                        return str(ffmpeg_path)
                except Exception:
                    continue
        
        # 檢查常見路徑
        for path in common_paths:
            if path.exists():
                return str(path)

        # 如果都找不到，顯示詳細的錯誤訊息
        error_msg = (
            "無法找到 FFmpeg，請確認安裝並設定環境變數\n"
            "目前的環境變數 PATH：\n" + 
            "\n".join(os.environ.get('PATH', '').split(os.pathsep))
        )
        raise FFmpegNotFoundError(error_msg)

    def _verify_vvc_support(self) -> None:
        """驗證 H.266/VVC 支援"""
        has_vvc, version = self.check_ffmpeg_version()
        if not has_vvc:
            raise VVCNotSupportedError(
                f"此 FFmpeg 版本 ({version}) 不支援 H.266/VVC 編碼"
            )

    def check_ffmpeg_version(self) -> Tuple[bool, str]:
        """檢查 FFmpeg 版本和支援的編碼器"""
        try:
            version_result = subprocess.run(
                [self.ffmpeg_path, "-version"],
                capture_output=True,
                text=True
            )
            version_info = version_result.stdout.split('\n')[0]
            
            encoders_result = subprocess.run(
                [self.ffmpeg_path, "-encoders"],
                capture_output=True,
                text=True
            )
            
            has_vvc = "libvvenc" in encoders_result.stdout
            return has_vvc, version_info
        except Exception as e:
            self.logger.error(f"檢查 FFmpeg 版本時發生錯誤: {e}")
            return False, str(e)

    def get_video_info(self, video_path: str) -> VideoInfo:
        """獲取視訊檔案資訊"""
        video_path = Path(video_path)
        if not video_path.exists():
            raise FileNotFoundError(f"找不到視訊檔案: {video_path}")

        info = VideoInfo()
        info.file_size = video_path.stat().st_size / (1024 * 1024)  # Convert to MB

        try:
            result = subprocess.run(
                [self.ffmpeg_path, "-i", str(video_path)],
                capture_output=True,
                text=True,
                encoding='utf-8'
            )
            
            stderr = result.stderr
            
            # 解析視訊流資訊
            if "Stream #0:0" in stderr:
                video_stream = stderr.split("Stream #0:0")[1].split("\n")[0]
                info.video_stream = video_stream.strip()
                
                # 解析解析度
                if "x" in video_stream:
                    for part in video_stream.split(","):
                        if "x" in part:
                            try:
                                width, height = map(int, part.strip().split("x"))
                                info.width = width
                                info.height = height
                            except ValueError:
                                pass
                
                # 解析 FPS
                if "fps" in video_stream.lower():
                    try:
                        fps_str = video_stream.split("fps")[0].split(",")[-1].strip()
                        info.fps = float(fps_str)
                    except ValueError:
                        pass
                
                # 解析位元率
                if "kb/s" in video_stream:
                    for part in video_stream.split(","):
                        if "kb/s" in part:
                            info.bitrate = part.strip()
                
            # 解析時長
            if "Duration:" in stderr:
                duration = stderr.split("Duration:")[1].split(",")[0].strip()
                info.duration = duration
                
        except Exception as e:
            self.logger.error(f"獲取視訊資訊時發生錯誤: {e}")
            
        return info

    def encode_to_h266(
        self,
        input_path: str,
        output_path: str,
        qp: int = 32,
        threads: int = 4,
        preset: str = "medium",
        gpu: bool = False
    ) -> bool:
        """
        使用 H.266/VVC 編碼器轉檔
        
        參數:
            input_path: 輸入檔案路徑
            output_path: 輸出檔案路徑
            qp: 量化參數 (20-50)
            threads: 執行緒數量
            preset: 編碼預設值 ("faster", "fast", "medium", "slow", "slower")
            gpu: 是否使用 GPU 加速 (需要支援的顯示卡)
        """
        input_path = Path(input_path)
        if not input_path.exists():
            raise FileNotFoundError(f"找不到輸入檔案: {input_path}")
            
        if preset not in self.VALID_PRESETS:
            raise ValueError(f"無效的預設值: {preset}。有效值為: {', '.join(self.VALID_PRESETS)}")
        
        command = []
        
        # GPU 加速選項必須在輸入檔案之前
        if gpu:
            command.extend([
                self.ffmpeg_path,
                "-hwaccel", "auto",
                "-i", str(input_path)
            ])
        else:
            command.extend([
                self.ffmpeg_path,
                "-i", str(input_path)
            ])
        
        command.extend([
            "-c:v", "libvvenc",
            "-qp", str(qp),
            "-preset", preset,
            "-threads", str(threads),
            "-c:a", "aac",
            "-b:a", "128k"
        ])
        
        # 如果輸出路徑已存在，在檔名後加上編號
        output_path = Path(output_path)
        if output_path.exists():
            index = 1
            while True:
                new_path = output_path.parent / f"{output_path.stem}_{index}{output_path.suffix}"
                if not new_path.exists():
                    output_path = new_path
                    break
                index += 1
        
        command.append(str(output_path))
        
        self.logger.info(f"執行命令: {' '.join(command)}")
        
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            while True:
                line = process.stderr.readline()
                if not line:
                    break
                try:
                    # 嘗試使用不同編碼解碼輸出
                    for encoding in ['utf-8', 'cp950', 'big5']:
                        try:
                            decoded_line = line.decode(encoding)
                            print(decoded_line, end='')
                            break
                        except UnicodeDecodeError:
                            continue
                except Exception:
                    # 如果所有編碼都失敗，跳過此行
                    continue
            
            process.communicate()
            
            if process.returncode == 0:
                self.logger.info(f"成功轉檔為 H.266 格式: {output_path}")
                return True
            else:
                self.logger.error("轉檔失敗!")
                return False
                
        except Exception as e:
            self.logger.error(f"編碼過程發生錯誤: {e}")
            return False

def main():
    """主程式"""
    print("=== H.266/VVC 視訊轉檔工具 ===\n")
    
    try:
        # 檢查 CPU 核心數，設定預設執行緒數
        cpu_cores = os.cpu_count() or 4
        default_threads = max(1, cpu_cores - 1)  # 預設使用 CPU 核心數減 1
        
        encoder = VideoEncoder()
        print(f"找到 FFmpeg: {encoder.ffmpeg_path}")
        
        _, version_info = encoder.check_ffmpeg_version()
        print(f"\nFFmpeg 版本: {version_info}")

        # 輸入視訊路徑
        while True:
            input_video = input("\n請輸入要轉檔的視訊路徑: ").strip('"').strip("'")
            input_path = Path(input_video)
            
            if input_path.exists():
                break
            print(f"錯誤: 找不到檔案 {input_video}")
        
        # 設定輸出檔案路徑
        output_path = input_path.parent / f"{input_path.stem}_h266{input_path.suffix}"
        
        # 設定編碼品質
        while True:
            try:
                qp = int(input("\n請輸入編碼品質 (20-50，越小品質越好，建議 32): ").strip())
                if 20 <= qp <= 50:
                    break
                print("請輸入 20-50 之間的數值！")
            except ValueError:
                print("請輸入有效的數字！")
        
        # 設定編碼預設值
        print("\n編碼預設值:")
        for i, preset in enumerate(encoder.VALID_PRESETS, 1):
            print(f"{i}. {preset} ", end='')
            if preset == "medium":
                print("(建議)", end='')
            print()
        
        while True:
            try:
                preset_index = int(input("請選擇編碼預設值 (1-5): ").strip())
                if 1 <= preset_index <= len(encoder.VALID_PRESETS):
                    preset = encoder.VALID_PRESETS[preset_index-1]
                    break
                print(f"請輸入 1 到 {len(encoder.VALID_PRESETS)} 之間的數值！")
            except ValueError:
                print("請輸入有效的數字！")
        
        # 設定執行緒數
        while True:
            try:
                threads = int(input(f"\n請輸入執行緒數量 (1-{cpu_cores}，建議 {default_threads}): ").strip())
                if 1 <= threads <= cpu_cores:
                    break
                print(f"請輸入 1 到 {cpu_cores} 之間的數值！")
            except ValueError:
                print("請輸入有效的數字！")
        
        # 詢問是否使用 GPU 加速
        try:
            use_gpu = input("\n是否使用 GPU 加速轉檔? (y/N): ").strip().lower() == 'y'
        except Exception:
            use_gpu = False
        
        # 顯示視訊資訊
        print("\n正在分析視訊資訊...")
        info = encoder.get_video_info(input_video)
        if info:
            print("\n視訊資訊:")
            if info.video_stream:
                print(f"影片流: {info.video_stream}")
            if info.duration:
                print(f"時長: {info.duration}")
            if info.width and info.height:
                print(f"解析度: {info.width}x{info.height}")
            if info.fps:
                print(f"幀率: {info.fps} fps")
            if info.bitrate:
                print(f"位元率: {info.bitrate}")
            print(f"檔案大小: {info.file_size:.1f} MB")
        
        # 顯示轉檔設定
        print("\n轉檔設定:")
        print(f"編碼品質 (QP): {qp}")
        print(f"預設值: {preset}")
        print(f"執行緒數: {threads}")
        print(f"GPU 加速: {'是' if use_gpu else '否'}")
        
        # 確認開始轉檔
        if input("\n確認開始轉檔? (Y/n): ").strip().lower() not in ['n', 'no']:
            # 開始轉檔
            print("\n開始轉檔為 H.266 格式...")
            print("(轉檔過程中會顯示進度，請稍候...)")
            
            success = encoder.encode_to_h266(
                input_path=input_video,
                output_path=output_path,
                qp=qp,
                threads=threads,
                preset=preset,
                gpu=use_gpu
            )
            
            if success:
                output_info = encoder.get_video_info(str(output_path))
                print(f"\n轉檔完成!")
                print(f"輸出檔案: {output_path}")
                
                # 顯示檔案大小比較
                print(f"\n原始檔案大小: {info.file_size:.1f} MB")
                print(f"轉檔後大小: {output_info.file_size:.1f} MB")
                reduction = ((info.file_size - output_info.file_size) / info.file_size * 100)
                print(f"壓縮率: {reduction:.1f}%")
                
                # 如果檔案反而變大，顯示警告
                if reduction < 0:
                    print("\n警告: 轉檔後的檔案大於原始檔案!")
                    print("可能原因:")
                    print("1. 原始檔案已經高度壓縮")
                    print("2. 選擇的品質參數 (QP) 過低")
                    print("3. 原始編碼格式可能更有效率")
            else:
                print("\n轉檔失敗，請檢查錯誤訊息。")
        else:
            print("\n已取消轉檔。")
        
        return success

    except FFmpegNotFoundError as e:
        print(f"\n錯誤: {e}")
        print("請確認以下事項：")
        print("1. 確認 FFmpeg 是否已正確安裝")
        print("2. 確認環境變數 PATH 中是否包含 FFmpeg 的路徑")
        print("3. 如果沒有安裝 FFmpeg，請：")
        print("   a. 從 https://ffmpeg.org/download.html 下載")
        print("   b. 解壓縮到適當的目錄")
        print("   c. 將含有 ffmpeg.exe 的 bin 目錄加入環境變數 PATH")
        return False
        
    except VVCNotSupportedError as e:
        print(f"\n錯誤: {e}")
        print("請確保安裝了支援 libvvenc 的 FFmpeg 版本。")
        return False

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n程式已被使用者中斷")
    except Exception as e:
        print(f"\n程式執行時發生錯誤: {str(e)}")
        logging.exception("未預期的錯誤")