import random
from pydub import AudioSegment
from io import BytesIO

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