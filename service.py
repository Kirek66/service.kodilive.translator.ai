import xbmc
import xbmcaddon
import xbmcvfs
import os
import re
import openai_client

MAX_LINE_LENGTH = 42
FAST_START_PERCENT = 15


def log(msg):
    xbmc.log(f"KodiLive SRT: {msg}", xbmc.LOGINFO)


def has_polish_chars(text):
    return any(c in text for c in "ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")


def clean_markdown(text):
    return text.replace("```srt", "").replace("```", "").strip()


def clean_sdh(text):
    text = re.sub(r"\[(.*?)\]", "", text)
    text = re.sub(r"\((.*?)\)", "", text)
    return text.strip()


def wrap_line(line, max_len=MAX_LINE_LENGTH):
    words = line.split()
    if not words:
        return line

    lines = []
    current = words[0]

    for w in words[1:]:
        if len(current) + len(w) + 1 <= max_len:
            current += " " + w
        else:
            lines.append(current)
            current = w

    lines.append(current)

    if len(lines) > 2:
        lines = [lines[0], " ".join(lines[1:])]

    return "\n".join(lines)


def fix_srt_format(text):
    blocks = text.split("\n\n")
    fixed = []

    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue

        num = lines[0]
        time = lines[1]

        body = clean_sdh(" ".join(lines[2:]))
        body = wrap_line(body)

        fixed.append("\n".join([num, time] + body.split("\n")))

    return "\n\n".join(fixed)


def get_temp_sub_file():
    try:
        path = xbmcvfs.translatePath("special://temp/")
        files = [
            os.path.join(path, f)
            for f in os.listdir(path)
            if f.lower().endswith(".srt")
        ]
        if not files:
            return None, 0
        newest = max(files, key=os.path.getmtime)
        return newest, os.path.getmtime(newest)
    except:
        return None, 0


def build_chunks(text, max_chars=5000):
    blocks = text.strip().split("\n\n")
    chunks = []
    current = ""

    for b in blocks:
        b += "\n\n"
        if len(current) + len(b) > max_chars:
            chunks.append(current.strip())
            current = b
        else:
            current += b

    if current.strip():
        chunks.append(current.strip())

    return chunks


def run():

    monitor = xbmc.Monitor()
    player = xbmc.Player()
    addon = xbmcaddon.Addon()

    sub_dir = "/storage/emulated/0/Kodi_Napisy/"
    if not xbmcvfs.exists(sub_dir):
        xbmcvfs.mkdir(sub_dir)

    last_mtime = 0

    while not monitor.abortRequested():

        if player.isPlayingVideo():

            sub_file, mtime = get_temp_sub_file()

            if sub_file and mtime != last_mtime:

                last_mtime = mtime
                log("NEW SUB DETECTED")

                api_key = addon.getSetting("api_key").strip()
                model_index = int(addon.getSetting("model") or 0)
                model = "gpt-4o-mini" if model_index == 0 else "gpt-4o"

                if not api_key:
                    continue

                f = xbmcvfs.File(sub_file, "r")
                original = f.read()
                f.close()

                if not original.strip():
                    continue

                if has_polish_chars(original):
                    continue

                prompt = (
                    "Translate SRT subtitles from English to Polish.\n"
                    "Keep numbering and timestamps unchanged.\n"
                    "Remove SDH descriptions.\n"
                    "Max 2 lines per subtitle.\n"
                    "Use natural, spoken Polish (avoid literal translations and English calques).\n"
                    "Determine grammatical gender based on context; use neutral forms if ambiguous.\n"
                    "Translate idioms and phrases by their meaning, using natural Polish equivalents.\n"
                    "Avoid overusing pronouns like 'Ty', 'On', 'Ona'—let the verb endings carry the meaning.\n"
                    "Do not add explanations or comments. Output ONLY translated subtitles.\n"
                    "Do not add explanations or comments. Output ONLY SRT."
                )

                chunks = build_chunks(original)
                translated_chunks = []

                quick_done = False

                for i, chunk in enumerate(chunks):

                    if not player.isPlaying():
                        break

                    response = openai_client.translate_text(
                        api_key, chunk, prompt, model
                    )

                    response = clean_markdown(response)
                    translated_chunks.append(response)

                    progress = int((len(translated_chunks)/len(chunks))*100)

                    if not quick_done and progress >= FAST_START_PERCENT:

                        quick_text = fix_srt_format(
                            "\n\n".join(translated_chunks)
                        )

                        quick_path = os.path.join(sub_dir, "quick_start.srt")

                        w = xbmcvfs.File(quick_path, "w")
                        w.write(quick_text)
                        w.close()

                        xbmc.sleep(300)
                        player.setSubtitles(quick_path)

                        xbmc.executebuiltin(
                            "Notification(KodiLive SRT, TURBO START!, 2500)"
                        )

                        quick_done = True

                if translated_chunks and player.isPlaying():

                    final_text = fix_srt_format(
                        "\n\n".join(translated_chunks)
                    )

                    video_tag = player.getVideoInfoTag()
                    title = video_tag.getTitle() or "Film"
                    clean_title = re.sub(r'[\\/*?:"<>|]', "", title).replace(" ", "_")

                    final_name = f"{clean_title}_TRANS_PL.srt"
                    final_path = os.path.join(sub_dir, final_name)

                    w = xbmcvfs.File(final_path, "w")
                    w.write(final_text)
                    w.close()

                    xbmc.sleep(300)
                    player.setSubtitles(final_path)

                    xbmc.executebuiltin(
                        "Notification(KodiLive SRT, Pelne napisy gotowe!, 3000)"
                    )

        if monitor.waitForAbort(3):
            break


if __name__ == "__main__":
    run()
