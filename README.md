# ClipKontrast

> Based on PeakCut (MIT License). Rebranded and modified as ClipKontrast.
>
> Guide by [@anistroz.ai](https://www.instagram.com/anistroz.ai/) (Instagram) and [@anistrozelite](https://www.youtube.com/@anistrozelite) (YouTube).
> Screenshots ke saath poori guide: folder mein **`SETUP-GUIDE.html`** kholo.

Lambi videos aur live streams se **captions wale vertical clips** (Reels / Shorts / TikTok) banao, apne hi computer pe.
Free hai, koi sign-in nahi chahiye.

## Windows: sabse aasaan tareeka (installer)

**[clipkontrast.com/download](https://clipkontrast.com/download)** se **`ClipKontrast-Setup.exe`** download karo, double-click karo, **Install** dabao. Bas.
Python, ffmpeg aur baaki sab isi ke andar hai: kuch alag se install nahi karna. Desktop pe ClipKontrast ka icon aa
jayega: wo ClipKontrast ko uski apni window mein kholta hai, normal software ki tarah (koi kaali window nahi, browser
tab nahi). Window band karo toh ClipKontrast band. "Windows protected your PC" aaye toh **More info**, phir **Run anyway**.
Naya version aane pe app khud batayega: **Update now** dabao, wo khud update hoke dobara khul jayega.
Tumhari clips aur settings har update mein safe rehti hain.

## Apne PC pe kaise chalaye: ZIP se (Mac, Linux, ya Windows bina installer ke)

**1. Download karo.** **[clipkontrast.com/download](https://clipkontrast.com/download)** kholo aur apne computer (Mac ya Linux) ka button dabao: ClipKontrast ki ZIP aa jayegi. Photos ke saath poori setup guide [yahan hai](https://drive.google.com/drive/folders/1BMRVHQ7vFiOQhX7m5j6kl7zmDWWRz7eq?usp=drive_link).

**2. Unzip karo, chhote folder mein.**
- **Windows:** ZIP pe right-click karo, phir **Extract All**, aur folder ko `C:\ClipKontrast` pe rakho.
  Desktop ya Downloads ke andar gehre folder mein mat rakhna: Windows lambe path pe speech model load nahi kar paata.
- **Mac:** ZIP pe double-click karo aur folder ko apne home folder mein rakh do.

**3. Start karo.**
- **Windows:** `Start-ClipKontrast-Windows.bat` pe double-click karo.
  "Windows protected your PC" aaye toh **More info** dabao, phir **Run anyway**.
- **Mac:** `Start-ClipKontrast-Mac.command` pe right-click karo, phir **Open**, phir dobara **Open** (pehli baar hi aisa karna hai).
- **Linux:** terminal mein `bash start-linux.sh` chalao.

Pehli baar 5-10 minute lagenge: script khud Python, ffmpeg aur baaki zaroori cheezein install karegi, aur speech model
(lagbhag 480 MB) download karegi. Phir browser apne aap khul jayega. Agli baar se bas wahi file double-click karni hai,
aur app kuch hi second mein khul jayega.

Jab tak app use kar rahe ho, kaali window (terminal) khuli rakhna. Use band karoge toh app bhi band ho jayega.

### AI key daalo (free, 2 minute)

AI key ke bina bhi clips bante hain, lekin sirf awaaz ki loudness dekh ke. Achhe clips ke liye:

1. https://aistudio.google.com/apikey pe jao aur **Create API key** dabao (Google ki free key).
2. ClipKontrast mein **Settings, AI** kholo, **Gemini** chuno, key paste karo, aur **Save and test** dabao.

Phir YouTube, Twitch ya Kick ka link paste karo aur **Make clips** dabao.

### Kuch problem aaye toh

| Problem | Kya karein |
|---|---|
| "winget is not available" | Microsoft Store se **App Installer** install karo, phir dobara chalao |
| "DLL load failed ... too long" | Folder ko `C:\ClipKontrast` pe le jao aur dobara chalao |
| Python install ke baad error | Window band karo aur `.bat` file dobara double-click karo |
| Browser nahi khula | Khud kholo: http://127.0.0.1:8765 |
| Mac: "cannot be opened" | Right-click karo, phir **Open** (double-click nahi) |

Zaroorat: Windows 10/11, macOS ya Linux, 8 GB RAM, lagbhag 3 GB khaali jagah. Video banne ka kaam tumhare
computer pe hota hai, aur tumhari videos kahin upload nahi hoti.

---

## Campaigns join karke paise kamao: [clipkontrast.com/earn](https://clipkontrast.com/earn)

Clips banake post karo, aur un clips ke views ke hisaab se paise kamao, seedha UPI pe.

1. **[clipkontrast.com/earn](https://clipkontrast.com/earn)** pe signup karo: email (6-digit OTP aayega) ya Google se.
2. **Payout profile** bharo: UPI ID, WhatsApp number, aur apne YouTube / Instagram / X / TikTok handles.
3. Koi live **campaign join** karo aur uske rules padho: kaunsa creator, kaunse platforms, kaunsa tag lagana hai, rate per 1,000 views.
4. Isi app se clips banao aur **apne account se post** karo, caption mein campaign ka tag lagake.
5. Clip ka **link website pe submit** karo. Hold period ke baad views gine jaate hain, admin approve karta hai, aur paise UPI pe aate hain.

Rules simple hain: clip tumhare apne account se aur campaign shuru hone ke baad post hona chahiye, aur paid hone tak public rehna chahiye.
Fake ya kharide hue views, edit kiye screenshots, ya kisi aur ka clip bhejoge toh kuch nahi milega aur account band ho sakta hai.

## Naya version kaise lein

Naya ZIP download karo aur usi folder mein extract karke files replace kar do. Tumhari videos aur clips (`data` folder) safe rehti hain.
Phir start file dobara chalao.

## Credits aur licence

ClipKontrast PeakCut pe based hai, jo MIT License ke tahat open source hai (LICENSE file dekho).
Caption fonts (`studio/fonts/`: Anton, Archivo Black, Poppins) SIL Open Font License ke tahat hain.

Sirf wahi videos clip karo jo tumhari hain ya jinki permission hai, aur jahan post karte ho un sites ke rules follow karo.

Guide by [@anistroz.ai](https://www.instagram.com/anistroz.ai/) · [@anistrozelite](https://www.youtube.com/@anistrozelite)
