"""Combined Steganography Toolkit GUI.

Loads each tool's stego.py from its own sibling folder (msg_in_image,
msg_in_audio, img_in_audio, img_in_video, msg_in_video) so those folders
stay standalone/self-contained, and presents all five as tabs.
"""

import os
import importlib.util
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_stego(folder_name):
    path = os.path.join(ROOT, folder_name, "stego.py")
    spec = importlib.util.spec_from_file_location(f"{folder_name}_stego", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


msg_image = _load_stego("msg_in_image")
msg_audio = _load_stego("msg_in_audio")
img_audio = _load_stego("img_in_audio")
img_video = _load_stego("img_in_video")
msg_video = _load_stego("msg_in_video")

IMAGE_TYPES = [("Image files", "*.png *.bmp *.jpg *.jpeg"), ("All files", "*.*")]
AUDIO_TYPES = [("WAV files", "*.wav"), ("All files", "*.*")]
VIDEO_TYPES = [("Video files", "*.avi *.mp4 *.mov *.mkv"), ("All files", "*.*")]


def browse_file(entry, filetypes):
    path = filedialog.askopenfilename(filetypes=filetypes)
    if path:
        entry.delete(0, tk.END)
        entry.insert(0, path)


def browse_save(entry, filetypes, default_ext):
    path = filedialog.asksaveasfilename(filetypes=filetypes, defaultextension=default_ext)
    if path:
        entry.delete(0, tk.END)
        entry.insert(0, path)


def path_row(parent, label_text, row, filetypes, save=False, default_ext=""):
    ttk.Label(parent, text=label_text).grid(row=row, column=0, sticky="w", padx=5, pady=4)
    entry = ttk.Entry(parent, width=55)
    entry.grid(row=row, column=1, padx=5, pady=4)
    cmd = (lambda: browse_save(entry, filetypes, default_ext)) if save else (lambda: browse_file(entry, filetypes))
    ttk.Button(parent, text="Browse...", command=cmd).grid(row=row, column=2, padx=5, pady=4)
    return entry


class MessageImageTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, padding=10)
        ttk.Label(self, text="Encode: hide a text message inside an image", font=("", 10, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 8)
        )
        self.enc_input = path_row(self, "Source image:", 1, IMAGE_TYPES)
        ttk.Label(self, text="Message:").grid(row=2, column=0, sticky="nw", padx=5, pady=4)
        self.enc_message = tk.Text(self, width=55, height=5)
        self.enc_message.grid(row=2, column=1, columnspan=2, padx=5, pady=4, sticky="w")
        self.enc_output = path_row(self, "Save output image as:", 3, [("PNG image", "*.png")], save=True, default_ext=".png")
        ttk.Button(self, text="Encode", command=self.do_encode).grid(row=4, column=1, pady=10, sticky="w")

        ttk.Separator(self, orient="horizontal").grid(row=5, column=0, columnspan=3, sticky="ew", pady=12)

        ttk.Label(self, text="Decode: extract a hidden text message from an image", font=("", 10, "bold")).grid(
            row=6, column=0, columnspan=3, sticky="w", pady=(0, 8)
        )
        self.dec_input = path_row(self, "Image with hidden message:", 7, IMAGE_TYPES)
        ttk.Button(self, text="Decode", command=self.do_decode).grid(row=8, column=1, pady=10, sticky="w")
        ttk.Label(self, text="Decoded message:").grid(row=9, column=0, sticky="nw", padx=5, pady=4)
        self.dec_output = tk.Text(self, width=55, height=5)
        self.dec_output.grid(row=9, column=1, columnspan=2, padx=5, pady=4, sticky="w")

    def do_encode(self):
        src = self.enc_input.get().strip()
        out = self.enc_output.get().strip()
        message = self.enc_message.get("1.0", tk.END).rstrip("\n")
        if not src or not out or not message:
            messagebox.showwarning("Missing info", "Please provide a source image, message, and output path.")
            return
        try:
            saved_to = msg_image.encode_message_in_image(src, message, out)
            messagebox.showinfo("Success", f"Message embedded successfully.\nSaved to: {saved_to}")
        except Exception as e:
            messagebox.showerror("Encoding failed", str(e))

    def do_decode(self):
        src = self.dec_input.get().strip()
        if not src:
            messagebox.showwarning("Missing info", "Please select an image.")
            return
        try:
            message = msg_image.decode_message_from_image(src)
            self.dec_output.delete("1.0", tk.END)
            self.dec_output.insert(tk.END, message)
        except Exception as e:
            messagebox.showerror("Decoding failed", str(e))


class MessageAudioTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, padding=10)
        ttk.Label(self, text="Encode: hide a text message inside a WAV audio file", font=("", 10, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 8)
        )
        self.enc_input = path_row(self, "Source audio (.wav):", 1, AUDIO_TYPES)
        ttk.Label(self, text="Message:").grid(row=2, column=0, sticky="nw", padx=5, pady=4)
        self.enc_message = tk.Text(self, width=55, height=5)
        self.enc_message.grid(row=2, column=1, columnspan=2, padx=5, pady=4, sticky="w")
        self.enc_output = path_row(self, "Save output audio as:", 3, AUDIO_TYPES, save=True, default_ext=".wav")
        ttk.Button(self, text="Encode", command=self.do_encode).grid(row=4, column=1, pady=10, sticky="w")

        ttk.Separator(self, orient="horizontal").grid(row=5, column=0, columnspan=3, sticky="ew", pady=12)

        ttk.Label(self, text="Decode: extract a hidden text message from an audio file", font=("", 10, "bold")).grid(
            row=6, column=0, columnspan=3, sticky="w", pady=(0, 8)
        )
        self.dec_input = path_row(self, "Audio with hidden message:", 7, AUDIO_TYPES)
        ttk.Button(self, text="Decode", command=self.do_decode).grid(row=8, column=1, pady=10, sticky="w")
        ttk.Label(self, text="Decoded message:").grid(row=9, column=0, sticky="nw", padx=5, pady=4)
        self.dec_output = tk.Text(self, width=55, height=5)
        self.dec_output.grid(row=9, column=1, columnspan=2, padx=5, pady=4, sticky="w")

    def do_encode(self):
        src = self.enc_input.get().strip()
        out = self.enc_output.get().strip()
        message = self.enc_message.get("1.0", tk.END).rstrip("\n")
        if not src or not out or not message:
            messagebox.showwarning("Missing info", "Please provide a source audio file, message, and output path.")
            return
        try:
            msg_audio.encode_message_in_audio(src, message, out)
            messagebox.showinfo("Success", f"Message embedded successfully.\nSaved to: {out}")
        except Exception as e:
            messagebox.showerror("Encoding failed", str(e))

    def do_decode(self):
        src = self.dec_input.get().strip()
        if not src:
            messagebox.showwarning("Missing info", "Please select an audio file.")
            return
        try:
            message = msg_audio.decode_message_from_audio(src)
            self.dec_output.delete("1.0", tk.END)
            self.dec_output.insert(tk.END, message)
        except Exception as e:
            messagebox.showerror("Decoding failed", str(e))


class ImageAudioTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, padding=10)
        ttk.Label(self, text="Encode: hide an entire image inside a WAV audio file", font=("", 10, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 8)
        )
        self.enc_image = path_row(self, "Image to hide:", 1, IMAGE_TYPES)
        self.enc_audio = path_row(self, "Source audio (.wav):", 2, AUDIO_TYPES)
        self.enc_output = path_row(self, "Save output audio as:", 3, AUDIO_TYPES, save=True, default_ext=".wav")
        ttk.Button(self, text="Encode", command=self.do_encode).grid(row=4, column=1, pady=10, sticky="w")

        ttk.Separator(self, orient="horizontal").grid(row=5, column=0, columnspan=3, sticky="ew", pady=12)

        ttk.Label(self, text="Decode: extract a hidden image from an audio file", font=("", 10, "bold")).grid(
            row=6, column=0, columnspan=3, sticky="w", pady=(0, 8)
        )
        self.dec_audio = path_row(self, "Audio with hidden image:", 7, AUDIO_TYPES)
        self.dec_output = path_row(self, "Save extracted image as:", 8, [("PNG image", "*.png")], save=True, default_ext=".png")
        ttk.Button(self, text="Decode", command=self.do_decode).grid(row=9, column=1, pady=10, sticky="w")

    def do_encode(self):
        image_path = self.enc_image.get().strip()
        audio_path = self.enc_audio.get().strip()
        out = self.enc_output.get().strip()
        if not image_path or not audio_path or not out:
            messagebox.showwarning("Missing info", "Please provide an image, source audio, and output path.")
            return
        try:
            img_audio.encode_image_in_audio(image_path, audio_path, out)
            messagebox.showinfo("Success", f"Image embedded successfully.\nSaved to: {out}")
        except Exception as e:
            messagebox.showerror("Encoding failed", str(e))

    def do_decode(self):
        audio_path = self.dec_audio.get().strip()
        out = self.dec_output.get().strip()
        if not audio_path or not out:
            messagebox.showwarning("Missing info", "Please provide an audio file and output path.")
            return
        try:
            img_audio.decode_image_from_audio(audio_path, out)
            messagebox.showinfo("Success", f"Image extracted successfully.\nSaved to: {out}")
        except Exception as e:
            messagebox.showerror("Decoding failed", str(e))


VIDEO_NOTE = ("Note: output is always saved as a lossless FFV1 .avi file -- "
              "any other format/codec would destroy the hidden bits.")


class MessageVideoTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, padding=10)
        ttk.Label(self, text="Encode: hide a text message inside a video", font=("", 10, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 8)
        )
        self.enc_input = path_row(self, "Source video:", 1, VIDEO_TYPES)
        ttk.Label(self, text="Message:").grid(row=2, column=0, sticky="nw", padx=5, pady=4)
        self.enc_message = tk.Text(self, width=55, height=5)
        self.enc_message.grid(row=2, column=1, columnspan=2, padx=5, pady=4, sticky="w")
        self.enc_output = path_row(self, "Save output video as:", 3, [("AVI video", "*.avi")], save=True, default_ext=".avi")
        ttk.Label(self, text=VIDEO_NOTE, foreground="#555", wraplength=560, justify="left").grid(
            row=4, column=0, columnspan=3, sticky="w", padx=5
        )
        ttk.Button(self, text="Encode", command=self.do_encode).grid(row=5, column=1, pady=10, sticky="w")

        ttk.Separator(self, orient="horizontal").grid(row=6, column=0, columnspan=3, sticky="ew", pady=12)

        ttk.Label(self, text="Decode: extract a hidden text message from a video", font=("", 10, "bold")).grid(
            row=7, column=0, columnspan=3, sticky="w", pady=(0, 8)
        )
        self.dec_input = path_row(self, "Video with hidden message:", 8, VIDEO_TYPES)
        ttk.Button(self, text="Decode", command=self.do_decode).grid(row=9, column=1, pady=10, sticky="w")
        ttk.Label(self, text="Decoded message:").grid(row=10, column=0, sticky="nw", padx=5, pady=4)
        self.dec_output = tk.Text(self, width=55, height=5)
        self.dec_output.grid(row=10, column=1, columnspan=2, padx=5, pady=4, sticky="w")

    def do_encode(self):
        src = self.enc_input.get().strip()
        out = self.enc_output.get().strip()
        message = self.enc_message.get("1.0", tk.END).rstrip("\n")
        if not src or not out or not message:
            messagebox.showwarning("Missing info", "Please provide a source video, message, and output path.")
            return
        try:
            saved_to = msg_video.encode_message_in_video(src, message, out)
            messagebox.showinfo("Success", f"Message embedded successfully.\nSaved to: {saved_to}")
        except Exception as e:
            messagebox.showerror("Encoding failed", str(e))

    def do_decode(self):
        src = self.dec_input.get().strip()
        if not src:
            messagebox.showwarning("Missing info", "Please select a video.")
            return
        try:
            message = msg_video.decode_message_from_video(src)
            self.dec_output.delete("1.0", tk.END)
            self.dec_output.insert(tk.END, message)
        except Exception as e:
            messagebox.showerror("Decoding failed", str(e))


class ImageVideoTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, padding=10)
        ttk.Label(self, text="Encode: hide an entire image inside a video", font=("", 10, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 8)
        )
        self.enc_image = path_row(self, "Image to hide:", 1, IMAGE_TYPES)
        self.enc_video = path_row(self, "Source video:", 2, VIDEO_TYPES)
        self.enc_output = path_row(self, "Save output video as:", 3, [("AVI video", "*.avi")], save=True, default_ext=".avi")
        ttk.Label(self, text=VIDEO_NOTE, foreground="#555", wraplength=560, justify="left").grid(
            row=4, column=0, columnspan=3, sticky="w", padx=5
        )
        ttk.Button(self, text="Encode", command=self.do_encode).grid(row=5, column=1, pady=10, sticky="w")

        ttk.Separator(self, orient="horizontal").grid(row=6, column=0, columnspan=3, sticky="ew", pady=12)

        ttk.Label(self, text="Decode: extract a hidden image from a video", font=("", 10, "bold")).grid(
            row=7, column=0, columnspan=3, sticky="w", pady=(0, 8)
        )
        self.dec_video = path_row(self, "Video with hidden image:", 8, VIDEO_TYPES)
        self.dec_output = path_row(self, "Save extracted image as:", 9, [("PNG image", "*.png")], save=True, default_ext=".png")
        ttk.Button(self, text="Decode", command=self.do_decode).grid(row=10, column=1, pady=10, sticky="w")

    def do_encode(self):
        image_path = self.enc_image.get().strip()
        video_path = self.enc_video.get().strip()
        out = self.enc_output.get().strip()
        if not image_path or not video_path or not out:
            messagebox.showwarning("Missing info", "Please provide an image, source video, and output path.")
            return
        try:
            saved_to = img_video.encode_image_in_video(image_path, video_path, out)
            messagebox.showinfo("Success", f"Image embedded successfully.\nSaved to: {saved_to}")
        except Exception as e:
            messagebox.showerror("Encoding failed", str(e))

    def do_decode(self):
        video_path = self.dec_video.get().strip()
        out = self.dec_output.get().strip()
        if not video_path or not out:
            messagebox.showwarning("Missing info", "Please provide a video file and output path.")
            return
        try:
            img_video.decode_image_from_video(video_path, out)
            messagebox.showinfo("Success", f"Image extracted successfully.\nSaved to: {out}")
        except Exception as e:
            messagebox.showerror("Decoding failed", str(e))


def main():
    root = tk.Tk()
    root.title("Steganography Toolkit")
    root.geometry("700x620")

    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True, padx=8, pady=8)

    notebook.add(MessageImageTab(notebook), text="Message <-> Image")
    notebook.add(MessageAudioTab(notebook), text="Message <-> Audio")
    notebook.add(ImageAudioTab(notebook), text="Image <-> Audio")
    notebook.add(MessageVideoTab(notebook), text="Message <-> Video")
    notebook.add(ImageVideoTab(notebook), text="Image <-> Video")

    root.mainloop()


if __name__ == "__main__":
    main()
