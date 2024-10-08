import re
import os
import glob
import random
from typing import List
from typing import Union

from loguru import logger
from moviepy.editor import *
from moviepy.video.tools.subtitles import SubtitlesClip
from PIL import ImageFont

from app.models import const
from app.models.schema import MaterialInfo, VideoAspect, VideoConcatMode, VideoParams, VideoClipParams
from app.utils import utils


def get_bgm_file(bgm_type: str = "random", bgm_file: str = ""):
    if not bgm_type:
        return ""

    if bgm_file and os.path.exists(bgm_file):
        return bgm_file

    if bgm_type == "random":
        suffix = "*.mp3"
        song_dir = utils.song_dir()
        files = glob.glob(os.path.join(song_dir, suffix))
        return random.choice(files)

    return ""


def combine_videos(
    combined_video_path: str,
    video_paths: List[str],
    audio_file: str,
    video_aspect: VideoAspect = VideoAspect.portrait,
    video_concat_mode: VideoConcatMode = VideoConcatMode.random,
    max_clip_duration: int = 5,
    threads: int = 2,
) -> str:
    audio_clip = AudioFileClip(audio_file)
    audio_duration = audio_clip.duration
    logger.info(f"max duration of audio: {audio_duration} seconds")
    # Required duration of each clip
    req_dur = audio_duration / len(video_paths)
    req_dur = max_clip_duration
    logger.info(f"each clip will be maximum {req_dur} seconds long")
    output_dir = os.path.dirname(combined_video_path)

    aspect = VideoAspect(video_aspect)
    video_width, video_height = aspect.to_resolution()

    clips = []
    video_duration = 0

    raw_clips = []
    for video_path in video_paths:
        clip = VideoFileClip(video_path).without_audio()
        clip_duration = clip.duration
        start_time = 0

        while start_time < clip_duration:
            end_time = min(start_time + max_clip_duration, clip_duration)
            split_clip = clip.subclip(start_time, end_time)
            raw_clips.append(split_clip)
            # logger.info(f"splitting from {start_time:.2f} to {end_time:.2f}, clip duration {clip_duration:.2f}, split_clip duration {split_clip.duration:.2f}")
            start_time = end_time
            if video_concat_mode.value == VideoConcatMode.sequential.value:
                break

    # random video_paths order
    if video_concat_mode.value == VideoConcatMode.random.value:
        random.shuffle(raw_clips)

    # Add downloaded clips over and over until the duration of the audio (max_duration) has been reached
    while video_duration < audio_duration:
        for clip in raw_clips:
            # Check if clip is longer than the remaining audio
            if (audio_duration - video_duration) < clip.duration:
                clip = clip.subclip(0, (audio_duration - video_duration))
            # Only shorten clips if the calculated clip length (req_dur) is shorter than the actual clip to prevent still image
            elif req_dur < clip.duration:
                clip = clip.subclip(0, req_dur)
            clip = clip.set_fps(30)

            # Not all videos are same size, so we need to resize them
            clip_w, clip_h = clip.size
            if clip_w != video_width or clip_h != video_height:
                clip_ratio = clip.w / clip.h
                video_ratio = video_width / video_height

                if clip_ratio == video_ratio:
                    # 等比例缩放
                    clip = clip.resize((video_width, video_height))
                else:
                    # 等比缩放视频
                    if clip_ratio > video_ratio:
                        # 按照目标宽度等比缩放
                        scale_factor = video_width / clip_w
                    else:
                        # 按照目标高度等比缩放
                        scale_factor = video_height / clip_h

                    new_width = int(clip_w * scale_factor)
                    new_height = int(clip_h * scale_factor)
                    clip_resized = clip.resize(newsize=(new_width, new_height))

                    background = ColorClip(
                        size=(video_width, video_height), color=(0, 0, 0)
                    )
                    clip = CompositeVideoClip(
                        [
                            background.set_duration(clip.duration),
                            clip_resized.set_position("center"),
                        ]
                    )

                logger.info(
                    f"resizing video to {video_width} x {video_height}, clip size: {clip_w} x {clip_h}"
                )

            if clip.duration > max_clip_duration:
                clip = clip.subclip(0, max_clip_duration)

            clips.append(clip)
            video_duration += clip.duration

    video_clip = concatenate_videoclips(clips)
    video_clip = video_clip.set_fps(30)
    logger.info("writing")
    # https://github.com/harry0703/NarratoAI/issues/111#issuecomment-2032354030
    video_clip.write_videofile(
        filename=combined_video_path,
        threads=threads,
        logger=None,
        temp_audiofile_path=output_dir,
        audio_codec="aac",
        fps=30,
    )
    video_clip.close()
    logger.success("completed")
    return combined_video_path


def wrap_text(text, max_width, font="Arial", fontsize=60):
    # 创建字体对象
    font = ImageFont.truetype(font, fontsize)

    def get_text_size(inner_text):
        inner_text = inner_text.strip()
        left, top, right, bottom = font.getbbox(inner_text)
        return right - left, bottom - top

    width, height = get_text_size(text)
    if width <= max_width:
        return text, height

    # logger.warning(f"wrapping text, max_width: {max_width}, text_width: {width}, text: {text}")

    processed = True

    _wrapped_lines_ = []
    words = text.split(" ")
    _txt_ = ""
    for word in words:
        _before = _txt_
        _txt_ += f"{word} "
        _width, _height = get_text_size(_txt_)
        if _width <= max_width:
            continue
        else:
            if _txt_.strip() == word.strip():
                processed = False
                break
            _wrapped_lines_.append(_before)
            _txt_ = f"{word} "
    _wrapped_lines_.append(_txt_)
    if processed:
        _wrapped_lines_ = [line.strip() for line in _wrapped_lines_]
        result = "\n".join(_wrapped_lines_).strip()
        height = len(_wrapped_lines_) * height
        # logger.warning(f"wrapped text: {result}")
        return result, height

    _wrapped_lines_ = []
    chars = list(text)
    _txt_ = ""
    for word in chars:
        _txt_ += word
        _width, _height = get_text_size(_txt_)
        if _width <= max_width:
            continue
        else:
            _wrapped_lines_.append(_txt_)
            _txt_ = ""
    _wrapped_lines_.append(_txt_)
    result = "\n".join(_wrapped_lines_).strip()
    height = len(_wrapped_lines_) * height
    # logger.warning(f"wrapped text: {result}")
    return result, height


def generate_video(
    video_path: str,
    audio_path: str,
    subtitle_path: str,
    output_file: str,
    params: Union[VideoParams, VideoClipParams],
):
    aspect = VideoAspect(params.video_aspect)
    video_width, video_height = aspect.to_resolution()

    logger.info(f"start, video size: {video_width} x {video_height}")
    logger.info(f"  ① video: {video_path}")
    logger.info(f"  ② audio: {audio_path}")
    logger.info(f"  ③ subtitle: {subtitle_path}")
    logger.info(f"  ④ output: {output_file}")

    # 写入与输出文件相同的目录
    output_dir = os.path.dirname(output_file)

    font_path = ""
    if params.subtitle_enabled:
        if not params.font_name:
            params.font_name = "STHeitiMedium.ttc"
        font_path = os.path.join(utils.font_dir(), params.font_name)
        if os.name == "nt":
            font_path = font_path.replace("\\", "/")

        logger.info(f"using font: {font_path}")

    def create_text_clip(subtitle_item):
        phrase = subtitle_item[1]
        max_width = video_width * 0.9
        wrapped_txt, txt_height = wrap_text(
            phrase, max_width=max_width, font=font_path, fontsize=params.font_size
        )
        _clip = TextClip(
            wrapped_txt,
            font=font_path,
            fontsize=params.font_size,
            color=params.text_fore_color,
            bg_color=params.text_background_color,
            stroke_color=params.stroke_color,
            stroke_width=params.stroke_width,
            print_cmd=False,
        )
        duration = subtitle_item[0][1] - subtitle_item[0][0]
        _clip = _clip.set_start(subtitle_item[0][0])
        _clip = _clip.set_end(subtitle_item[0][1])
        _clip = _clip.set_duration(duration)
        if params.subtitle_position == "bottom":
            _clip = _clip.set_position(("center", video_height * 0.95 - _clip.h))
        elif params.subtitle_position == "top":
            _clip = _clip.set_position(("center", video_height * 0.05))
        elif params.subtitle_position == "custom":
            # 确保字幕完全在屏幕内
            margin = 10  # 额外的边距，单位为像素
            max_y = video_height - _clip.h - margin
            min_y = margin
            custom_y = (video_height - _clip.h) * (params.custom_position / 100)
            custom_y = max(min_y, min(custom_y, max_y))  # 限制 y 值在有效范围内
            _clip = _clip.set_position(("center", custom_y))
        else:  # center
            _clip = _clip.set_position(("center", "center"))
        return _clip

    video_clip = VideoFileClip(video_path)
    audio_clip = AudioFileClip(audio_path).volumex(params.voice_volume)

    if subtitle_path and os.path.exists(subtitle_path):
        sub = SubtitlesClip(subtitles=subtitle_path, encoding="utf-8")
        text_clips = []
        for item in sub.subtitles:
            clip = create_text_clip(subtitle_item=item)
            text_clips.append(clip)
        video_clip = CompositeVideoClip([video_clip, *text_clips])

    bgm_file = get_bgm_file(bgm_type=params.bgm_type, bgm_file=params.bgm_file)
    if bgm_file:
        try:
            bgm_clip = (
                AudioFileClip(bgm_file).volumex(params.bgm_volume).audio_fadeout(3)
            )
            bgm_clip = afx.audio_loop(bgm_clip, duration=video_clip.duration)
            audio_clip = CompositeAudioClip([audio_clip, bgm_clip])
        except Exception as e:
            logger.error(f"failed to add bgm: {str(e)}")

    video_clip = video_clip.set_audio(audio_clip)
    video_clip.write_videofile(
        output_file,
        audio_codec="aac",
        temp_audiofile_path=output_dir,
        threads=params.n_threads,
        logger=None,
        fps=30,
    )
    video_clip.close()
    del video_clip
    logger.success(""
                   "completed")


def generate_video_v2(
        video_path: str,
        audio_path: str,
        subtitle_path: str,
        output_file: str,
        params: Union[VideoParams, VideoClipParams],
):
    """
    合并所有素材
    Args:
        video_path: 视频路径
        audio_path: 单个音频文件路径
        subtitle_path: 字幕文件路径
        output_file: 输出文件路径
        params: 视频参数

    Returns:

    """
    aspect = VideoAspect(params.video_aspect)
    video_width, video_height = aspect.to_resolution()

    logger.info(f"开始，视频尺寸: {video_width} x {video_height}")
    logger.info(f"  ① 视频: {video_path}")
    logger.info(f"  ② 音频: {audio_path}")
    logger.info(f"  ③ 字幕: {subtitle_path}")
    logger.info(f"  ④ 输出: {output_file}")

    # 写入与输出文件相同的目录
    output_dir = os.path.dirname(output_file)

    # 字体设置部分保持不变
    font_path = ""
    if params.subtitle_enabled:
        if not params.font_name:
            params.font_name = "STHeitiMedium.ttc"
        font_path = os.path.join(utils.font_dir(), params.font_name)
        if os.name == "nt":
            font_path = font_path.replace("\\", "/")
        logger.info(f"使用字体: {font_path}")

    # create_text_clip 函数保持不变
    def create_text_clip(subtitle_item):
        phrase = subtitle_item[1]
        max_width = video_width * 0.9
        wrapped_txt, txt_height = wrap_text(
            phrase, max_width=max_width, font=font_path, fontsize=params.font_size
        )
        _clip = TextClip(
            wrapped_txt,
            font=font_path,
            fontsize=params.font_size,
            color=params.text_fore_color,
            bg_color=params.text_background_color,
            stroke_color=params.stroke_color,
            stroke_width=params.stroke_width,
            print_cmd=False,
        )
        duration = subtitle_item[0][1] - subtitle_item[0][0]
        _clip = _clip.set_start(subtitle_item[0][0])
        _clip = _clip.set_end(subtitle_item[0][1])
        _clip = _clip.set_duration(duration)
        if params.subtitle_position == "bottom":
            _clip = _clip.set_position(("center", video_height * 0.95 - _clip.h))
        elif params.subtitle_position == "top":
            _clip = _clip.set_position(("center", video_height * 0.05))
        elif params.subtitle_position == "custom":
            # 确保字幕完全在屏幕内
            margin = 10  # 额外的边距，单位为像素
            max_y = video_height - _clip.h - margin
            min_y = margin
            custom_y = (video_height - _clip.h) * (params.custom_position / 100)
            custom_y = max(min_y, min(custom_y, max_y))  # 限制 y 值在有效范围内
            _clip = _clip.set_position(("center", custom_y))
        else:  # center
            _clip = _clip.set_position(("center", "center"))
        return _clip

    video_clip = VideoFileClip(video_path)
    original_audio = video_clip.audio  # 保存原始视频的音轨
    video_duration = video_clip.duration

    # 处理新的音频文件
    new_audio = AudioFileClip(audio_path).volumex(params.voice_volume)

    # 字幕处理部分
    if subtitle_path and os.path.exists(subtitle_path):
        sub = SubtitlesClip(subtitles=subtitle_path, encoding="utf-8")
        text_clips = []
        
        for item in sub.subtitles:
            clip = create_text_clip(subtitle_item=item)
            
            # 确保字幕的开始时间不早于视频开始
            start_time = max(clip.start, 0)
            
            # 如果字幕的开始时间晚于视频结束时间，则跳过此字幕
            if start_time >= video_duration:
                continue
            
            # 调整字幕的结束时间，但不要超过视频长度
            end_time = min(clip.end, video_duration)
            
            # 调整字幕的时间范围
            clip = clip.set_start(start_time).set_end(end_time)
            
            text_clips.append(clip)
        
        logger.info(f"处理了 {len(text_clips)} 段字幕")
        
        # 创建一个新的视频剪辑，包含所有字幕
        video_clip = CompositeVideoClip([video_clip, *text_clips])

    # 背景音乐处理部分
    bgm_file = get_bgm_file(bgm_type=params.bgm_type, bgm_file=params.bgm_file)
    
    # 合并音频轨道
    audio_tracks = [original_audio, new_audio]
    
    if bgm_file:
        try:
            bgm_clip = (
                AudioFileClip(bgm_file).volumex(params.bgm_volume).audio_fadeout(3)
            )
            bgm_clip = afx.audio_loop(bgm_clip, duration=video_duration)
            audio_tracks.append(bgm_clip)
        except Exception as e:
            logger.error(f"添加背景音乐失败: {str(e)}")

    # 合并所有音频轨道
    final_audio = CompositeAudioClip(audio_tracks)

    video_clip = video_clip.set_audio(final_audio)
    video_clip.write_videofile(
        output_file,
        audio_codec="aac",
        temp_audiofile_path=output_dir,
        threads=params.n_threads,
        logger=None,
        fps=30,
    )
    video_clip.close()
    del video_clip
    logger.success("完成")


def preprocess_video(materials: List[MaterialInfo], clip_duration=4):
    for material in materials:
        if not material.url:
            continue

        ext = utils.parse_extension(material.url)
        try:
            clip = VideoFileClip(material.url)
        except Exception:
            clip = ImageClip(material.url)

        width = clip.size[0]
        height = clip.size[1]
        if width < 480 or height < 480:
            logger.warning(f"video is too small, width: {width}, height: {height}")
            continue

        if ext in const.FILE_TYPE_IMAGES:
            logger.info(f"processing image: {material.url}")
            # 创建一个图片剪辑，并设置持续时间为3秒钟
            clip = (
                ImageClip(material.url)
                .set_duration(clip_duration)
                .set_position("center")
            )
            # 使用resize方法来添加缩放效果。这里使用了lambda函数来使得缩放效果随时间变化。
            # 假设我们想要从原始大小逐渐放大到120%的大小。
            # t代表当前时间，clip.duration为视频总时长，这里是3秒。
            # 注意：1 表示100%的大小，所以1.2表示120%的大小
            zoom_clip = clip.resize(
                lambda t: 1 + (clip_duration * 0.03) * (t / clip.duration)
            )

            # 如果需要，可以创建一个包含缩放剪辑的复合视频剪辑
            # （这在您想要在视频中添加其他元素时非常有用）
            final_clip = CompositeVideoClip([zoom_clip])

            # 输出视频
            video_file = f"{material.url}.mp4"
            final_clip.write_videofile(video_file, fps=30, logger=None)
            final_clip.close()
            del final_clip
            material.url = video_file
            logger.success(f"completed: {video_file}")
    return materials


def combine_clip_videos(combined_video_path: str,
                        video_paths: List[str],
                        video_ost_list: List[bool],
                        list_script: list,
                        video_aspect: VideoAspect = VideoAspect.portrait,
                        threads: int = 2,
                        ) -> str:
    """
    合并子视频
    Args:
        combined_video_path: 合并后的存储路径
        video_paths: 子视频路径列表
        video_ost_list: 原声播放列表
        list_script: 剪辑脚本
        video_aspect: 屏幕比例
        threads: 线程数

    Returns:

    """
    from app.utils.utils import calculate_total_duration
    audio_duration = calculate_total_duration(list_script)
    logger.info(f"音频的最大持续时间: {audio_duration} s")
    # 每个剪辑所需的持续时间
    req_dur = audio_duration / len(video_paths)
    # req_dur = max_clip_duration
    # logger.info(f"每个剪辑的最大长度为 {req_dur} s")
    output_dir = os.path.dirname(combined_video_path)

    aspect = VideoAspect(video_aspect)
    video_width, video_height = aspect.to_resolution()

    clips = []
    video_duration = 0
    # 一遍又一遍地添加下载的剪辑，直到达到音频的持续时间 （max_duration）
    # while video_duration < audio_duration:
    for video_path, video_ost in zip(video_paths, video_ost_list):
        cache_video_path = utils.root_dir()
        clip = VideoFileClip(os.path.join(cache_video_path, video_path))
        # 通过 ost 字段判断是否播放原声
        if not video_ost:
            clip = clip.without_audio()
        # # 检查剪辑是否比剩余音频长
        # if (audio_duration - video_duration) < clip.duration:
        #     clip = clip.subclip(0, (audio_duration - video_duration))
        # # 仅当计算出的剪辑长度 （req_dur） 短于实际剪辑时，才缩短剪辑以防止静止图像
        # elif req_dur < clip.duration:
        #     clip = clip.subclip(0, req_dur)
        clip = clip.set_fps(30)

        # 并非所有视频的大小都相同，因此我们需要调整它们的大小
        clip_w, clip_h = clip.size
        if clip_w != video_width or clip_h != video_height:
            clip_ratio = clip.w / clip.h
            video_ratio = video_width / video_height

            if clip_ratio == video_ratio:
                # 等比例缩放
                clip = clip.resize((video_width, video_height))
            else:
                # 等比缩放视频
                if clip_ratio > video_ratio:
                    # 按照目标宽度等比缩放
                    scale_factor = video_width / clip_w
                else:
                    # 按照目标高度等比缩放
                    scale_factor = video_height / clip_h

                new_width = int(clip_w * scale_factor)
                new_height = int(clip_h * scale_factor)
                clip_resized = clip.resize(newsize=(new_width, new_height))

                background = ColorClip(size=(video_width, video_height), color=(0, 0, 0))
                clip = CompositeVideoClip([
                    background.set_duration(clip.duration),
                    clip_resized.set_position("center")
                ])

            logger.info(f"将视频 {video_path} 大小调整为 {video_width} x {video_height}, 剪辑尺寸: {clip_w} x {clip_h}")

        clips.append(clip)
        video_duration += clip.duration

    video_clip = concatenate_videoclips(clips)
    video_clip = video_clip.set_fps(30)
    logger.info(f"合并视频中...")
    video_clip.write_videofile(filename=combined_video_path,
                               threads=threads,
                               logger=None,
                               temp_audiofile_path=output_dir,
                               audio_codec="aac",
                               fps=30,
                               )
    video_clip.close()
    logger.success(f"completed")
    return combined_video_path


if __name__ == "__main__":
    # combined_video_path = "../../storage/tasks/12312312/com123.mp4"
    #
    # video_paths = ['../../storage/cache_videos/vid-00_00-00_03.mp4',
    #                '../../storage/cache_videos/vid-00_03-00_07.mp4',
    #                '../../storage/cache_videos/vid-00_12-00_17.mp4',
    #                '../../storage/cache_videos/vid-00_26-00_31.mp4']
    # video_ost_list = [False, True, False, True]
    # list_script = [
    #     {
    #         "picture": "夜晚，一个小孩在树林里奔跑，后面有人拿着火把在追赶",
    #         "timestamp": "00:00-00:03",
    #         "narration": "夜黑风高的树林，一个小孩在拼命奔跑，后面的人穷追不舍！",
    #         "OST": False,
    #         "new_timestamp": "00:00-00:03"
    #     },
    #     {
    #         "picture": "追赶的人命令抓住小孩",
    #         "timestamp": "00:03-00:07",
    #         "narration": "原声播放1",
    #         "OST": True,
    #         "new_timestamp": "00:03-00:07"
    #     },
    #     {
    #         "picture": "小孩躲在草丛里，黑衣人用脚踢了踢他",
    #         "timestamp": "00:12-00:17",
    #         "narration": "小孩脱下外套，跑进树林, 一路奔跑，直到第二天清晨",
    #         "OST": False,
    #         "new_timestamp": "00:07-00:12"
    #     },
    #     {
    #         "picture": "小孩跑到车前，慌慌张张地对女人说有人要杀他",
    #         "timestamp": "00:26-00:31",
    #         "narration": "原声播放2",
    #         "OST": True,
    #         "new_timestamp": "00:12-00:17"
    #     }
    # ]
    # combine_clip_videos(combined_video_path=combined_video_path, video_paths=video_paths, video_ost_list=video_ost_list, list_script=list_script)

    cfg = VideoClipParams()
    cfg.video_aspect = VideoAspect.portrait
    cfg.font_name = "STHeitiMedium.ttc"
    cfg.font_size = 60
    cfg.stroke_color = "#000000"
    cfg.stroke_width = 1.5
    cfg.text_fore_color = "#FFFFFF"
    cfg.text_background_color = "transparent"
    cfg.bgm_type = "random"
    cfg.bgm_file = ""
    cfg.bgm_volume = 1.0
    cfg.subtitle_enabled = True
    cfg.subtitle_position = "bottom"
    cfg.n_threads = 2
    cfg.paragraph_number = 1

    cfg.voice_volume = 1.0

    # generate_video(video_path=video_file,
    #                audio_path=audio_file,
    #                subtitle_path=subtitle_file,
    #                output_file=output_file,
    #                params=cfg
    #                )

    video_path = "../../storage/tasks/7f5ae494-abce-43cf-8f4f-4be43320eafa/combined-1.mp4"

    audio_path = "../../storage/tasks/7f5ae494-abce-43cf-8f4f-4be43320eafa/audio_00-00-00-07.mp3"

    subtitle_path = "../../storage/tasks/7f5ae494-abce-43cf-8f4f-4be43320eafa\subtitle.srt"

    output_file = "../../storage/tasks/7f5ae494-abce-43cf-8f4f-4be43320eafa/final-123.mp4"

    generate_video_v2(video_path=video_path,
                       audio_path=audio_path,
                       subtitle_path=subtitle_path,
                       output_file=output_file,
                       params=cfg
                      )
