import xbmc, xbmcaddon, xbmcvfs, os, re, openai_client

MAX_LINE_LENGTH = 38

def log(msg):
    xbmc.log(f"KodiLive SRT: {msg}", xbmc.LOGINFO)

def has_polish_chars(text):
    return any(c in text for c in "ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")

def clean_markdown(text):
    return text.replace("```srt", "").replace("```", "").strip()

def strip_html(text):
    return re.sub(r'<[^>]*>', '', text)

def clean_sdh(text):
    text = re.sub(r"\[(.*?)\]", "", text)
    text = re.sub(r"\((.*?)\)", "", text)
    return text.strip()

def clean_empty_dialogues(text):
    blocks = text.strip().split("\n\n")
    cleaned_blocks = []
    for block in blocks:
        lines = block.split("\n")
        if len(lines) >= 3:
            body = "\n".join(lines[2:])
            # Jeśli to reklama strony www - pomiń
            if "www." in body.lower() or ".org" in body.lower():
                continue
            # Jeśli w bloku jest jakakolwiek litera lub cyfra - zostaw go
            if re.search(r'[a-zA-Z0-9]', strip_html(body)):
                cleaned_blocks.append(block)
    return "\n\n".join(cleaned_blocks)

def remove_song_lines(text):
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if re.search(r"[♪♫♬♩]", stripped): continue
        if stripped.startswith("#"): continue
        if re.match(r"^\(.*\)$", stripped) and stripped.upper() == stripped: continue
        cleaned.append(line)
    return "\n".join(cleaned)

def remove_speaker_prefix(text):
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        line = re.sub(r"^[A-ZŁŚŻŹĆŃÓ][A-Za-zŁŚŻŹĆŃÓąćęłńóśźż\-']{1,20}:\s*", "", line)
        line = re.sub(r"^[A-Z ]{2,20}:\s*", "", line)
        cleaned.append(line)
    return "\n".join(cleaned)

def wrap_line(line, max_len=MAX_LINE_LENGTH):
    words = line.split()
    if not words: return line
    lines, current = [], words[0]
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
    # Najpierw usuwamy kody HTML (kolory), które psują wyświetlanie w Kodi
    text = strip_html(text)
    blocks = text.split("\n\n")
    fixed = []
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 3: continue
        num, time = lines[0], lines[1]
        body_text = " ".join(lines[2:])
        
        # Jeśli po oczyszczeniu nie ma tekstu - pomiń
        if not re.search(r'[a-zA-Z0-9]', body_text): continue

        body_text = clean_sdh(body_text)
        body_text = remove_song_lines(body_text)
        body_text = remove_speaker_prefix(body_text)

        body = wrap_line(body_text.strip())
        if not body.strip(): continue

        fixed.append("\n".join([num, time] + body.split("\n")))
    return "\n\n".join(fixed)

def get_temp_sub_file():
    try:
        path = xbmcvfs.translatePath("special://temp/")
        files = [os.path.join(path, f) for f in os.listdir(path) if f.lower().endswith(".srt")]
        if not files: return None, 0
        newest = max(files, key=os.path.getmtime)
        return newest, os.path.getmtime(newest)
    except: return None, 0

def build_chunks(text, max_chars=5000):
    text = clean_empty_dialogues(text)
    blocks = text.strip().split("\n\n")
    chunks, current = [], ""
    for b in blocks:
        if len(current) + len(b) > max_chars:
            chunks.append(current.strip())
            current = b + "\n\n"
        else:
            current += b + "\n\n"
    if current.strip(): chunks.append(current.strip())
    return chunks

def run():
    monitor, player, addon = xbmc.Monitor(), xbmc.Player(), xbmcaddon.Addon()
    sub_dir = "/storage/emulated/0/Kodi_Napisy/" if xbmc.getCondVisibility('System.Platform.Android') else xbmcvfs.translatePath("special://home/Kodi_Napisy/")
    if not xbmcvfs.exists(sub_dir): xbmcvfs.mkdir(sub_dir)
    last_mtime = 0

    while not monitor.abortRequested():
        if player.isPlayingVideo():
            sub_file, mtime = get_temp_sub_file()
            if sub_file and mtime != last_mtime:
                last_mtime = mtime
                api_key = addon.getSetting("api_key").strip()
                model_idx = int(addon.getSetting("model") or 0)
                model = "gpt-4o-mini" if model_idx == 0 else "gpt-4o"
                if not api_key: continue

                f = xbmcvfs.File(sub_file, "r")
                original = f.read()
                f.close()
                if not original.strip() or has_polish_chars(original): continue

                prompt = (
                    "Translate SRT subtitles from English to Polish.\n"
                    "Keep numbering and timestamps unchanged.\n"
                    "Remove SDH descriptions.\n"
                    "Max 2 lines per subtitle.\n"
                    "Use natural, spoken Polish (avoid literal translations).\n"
                    "Determine grammatical gender based on context.\n"
                    "Translate idioms by meaning.\n"
                    "Avoid overusing pronouns like 'Ty', 'On', 'Ona'.\n"
                    "Output ONLY SRT."
                )

                chunks = build_chunks(original)
                if not chunks: continue
                
                translated_chunks, last_notified = [], -1
                title = player.getVideoInfoTag().getTitle() or "Film"
                safe_title = re.sub(r'[\\/*?:"<>|]', '', title).replace(' ', '_')
                final_path = os.path.join(sub_dir, safe_title + "_TRANS_PL.srt")

                for chunk in chunks:
                    if not player.isPlaying(): break
                    response = None
                    for attempt in range(3):
                        try:
                            response = openai_client.translate_text(api_key, chunk, prompt, model)
                            if response: break
                        except: xbmc.sleep(2000)
                    
                    if not response: break
                    translated_chunks.append(clean_markdown(response))
                    progress = int((len(translated_chunks)/len(chunks))*100)

                    if len(translated_chunks) == 1 or (progress // 10 > last_notified // 10):
                        last_notified = progress
                        w = xbmcvfs.File(final_path, "w")
                        w.write(fix_srt_format("\n\n".join(translated_chunks)))
                        w.close()
                        player.setSubtitles(final_path)
                        xbmc.executebuiltin(f"Notification(KodiLive SRT, Przetłumaczono {progress}%, 1500)")

                if translated_chunks and player.isPlaying():
                    w = xbmcvfs.File(final_path, "w")
                    w.write(fix_srt_format("\n\n".join(translated_chunks)))
                    w.close()
                    player.setSubtitles(final_path)
                    xbmc.executebuiltin("Notification(KodiLive SRT, Plik zapisany, 3000)")

        if monitor.waitForAbort(3): break

if __name__ == "__main__": run()
