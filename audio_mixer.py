import random
from pydub import AudioSegment
from io import BytesIO
import os

def create_silence(min_ms=300, max_ms=800):
    """ランダムな長さの無音を作成する"""
    duration = random.randint(min_ms, max_ms)
    return AudioSegment.silent(duration=duration)

def combine_audio_with_ma(script_data, client_openai, speed=1.0):
    """
    台本データ(JSON)を受け取り、セリフごとに音声を生成して
    「間」を挟みながら結合する関数
    """
    
    # 空のオーディオトラックを作成
    full_audio = AudioSegment.empty()
    
    # 最初のBGM的な無音（少し溜める）
    full_audio += AudioSegment.silent(duration=500)

    print("--- 音声結合処理開始 ---")

    for index, item in enumerate(script_data):
        voice = item.get("voice", "alloy") # 指定された声を使う
        text = item.get("text", "")
        
        if not text:
            continue

        print(f"Generating: {voice} - {text[:10]}...")

        # 1. 音声生成 (OpenAI TTS)
        try:
            response = client_openai.audio.speech.create(
                model="tts-1",
                voice=voice,
                input=text,
                speed=speed # 速度も反映させる
            )
            
            # バイナリデータをAudioSegmentに変換
            audio_data = BytesIO(response.content)
            segment = AudioSegment.from_file(audio_data, format="mp3")
            
            # 2. トラックに追加
            full_audio += segment
            
            # 3. 「間」を追加（最後のセリフ以外）
            if index < len(script_data) - 1:
                # ランダムな間を生成 (例: 0.3秒〜0.8秒)
                ma = create_silence(300, 800)
                full_audio += ma
                
        except Exception as e:
            print(f"Error generating voice for line {index}: {e}")
            continue

    print("--- 音声結合完了 ---")
    
    # 一時ファイルとして書き出し
    output_filename = "radio_output.mp3"
    full_audio.export(output_filename, format="mp3")
    
    return output_filename

def _load_audio(audio_source, audio_format=None):
    if isinstance(audio_source, bytes):
        return AudioSegment.from_file(BytesIO(audio_source), format=audio_format)

    if hasattr(audio_source, "read"):
        current_position = None
        if hasattr(audio_source, "tell") and hasattr(audio_source, "seek"):
            current_position = audio_source.tell()
            audio_source.seek(0)
        segment = AudioSegment.from_file(audio_source, format=audio_format)
        if current_position is not None:
            audio_source.seek(current_position)
        return segment

    return AudioSegment.from_file(audio_source, format=audio_format)

def _load_mp3(audio_source):
    return _load_audio(audio_source, audio_format="mp3")

def _loop_to_duration(audio, duration_ms):
    if len(audio) == 0:
        return AudioSegment.silent(duration=duration_ms)

    looped_audio = AudioSegment.empty()
    while len(looped_audio) < duration_ms:
        looped_audio += audio
    return looped_audio[:duration_ms]

def overlay_bgm(base_audio, bgm_audio, bgm_gain_db=-22, fade_in_ms=700, fade_out_ms=1000):
    """
    base_audioの長さに合わせてBGMをループ/カットし、薄く重ねる。
    """
    if len(base_audio) == 0:
        return base_audio

    bgm = _loop_to_duration(bgm_audio, len(base_audio))
    bgm = bgm + bgm_gain_db
    bgm = bgm.fade_in(min(fade_in_ms, len(bgm)))
    bgm = bgm.fade_out(min(fade_out_ms, len(bgm)))
    return base_audio.overlay(bgm)

def combine_intro_main_outro(
    intro_audio,
    main_audio,
    outro_audio,
    silence_seconds=2.5,
    output_path="final_episode.mp3",
    bgm_audio=None,
    bgm_gain_db=-28,
    bgm_format=None,
    fade_in_ms=700,
    fade_out_ms=1000,
    bgm_tail_seconds=5.0
):
    """
    intro、本編、outroのMP3を無音でつなぎ、完成版MP3を書き出す。
    BGMがある場合は番組全体に薄く重ね、末尾にBGMだけの余韻を入れる。
    """
    silence_ms = max(0, int(silence_seconds * 1000))
    gap = AudioSegment.silent(duration=silence_ms)

    intro = _load_mp3(intro_audio)
    main = _load_mp3(main_audio)
    outro = _load_mp3(outro_audio)

    final_audio = intro + gap + main + gap + outro

    if bgm_audio:
        bgm = _load_audio(bgm_audio, audio_format=bgm_format)
        tail = AudioSegment.silent(duration=max(0, int(bgm_tail_seconds * 1000)))
        final_audio += tail
        bgm_bed = _loop_to_duration(bgm, len(final_audio))
        bgm_bed = bgm_bed + bgm_gain_db
        bgm_bed = bgm_bed.fade_in(min(fade_in_ms, len(bgm_bed)))
        bgm_bed = bgm_bed.fade_out(min(fade_out_ms, len(bgm_bed)))
        final_audio = final_audio.overlay(bgm_bed)

    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    final_audio.export(output_path, format="mp3")
    return output_path
