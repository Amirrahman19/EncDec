"""Standalone GUI: hide/extract an entire image inside a WAV audio file."""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from stego import encode_image_in_audio, decode_image_from_audio

IMAGE_TYPES = [("Image files", "*.png *.bmp *.jpg *.jpeg"), ("All files", "*.*")]
AUDIO_TYPES = [("WAV files", "*.wav"), ("All files", "*.*")]


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


def main():
    root = tk.Tk()
    root.title("Image <-> Audio")
    root.geometry("660x420")
    frame = ttk.Frame(root, padding=10)
    frame.pack(fill="both", expand=True)

    ttk.Label(frame, text="Encode: hide an entire image inside a WAV audio file", font=("", 10, "bold")).grid(
        row=0, column=0, columnspan=3, sticky="w", pady=(0, 8)
    )
    enc_image = path_row(frame, "Image to hide:", 1, IMAGE_TYPES)
    enc_audio = path_row(frame, "Source audio (.wav):", 2, AUDIO_TYPES)
    enc_output = path_row(frame, "Save output audio as:", 3, AUDIO_TYPES, save=True, default_ext=".wav")

    def do_encode():
        image_path = enc_image.get().strip()
        audio_path = enc_audio.get().strip()
        out = enc_output.get().strip()
        if not image_path or not audio_path or not out:
            messagebox.showwarning("Missing info", "Please provide an image, source audio, and output path.")
            return
        try:
            encode_image_in_audio(image_path, audio_path, out)
            messagebox.showinfo("Success", f"Image embedded successfully.\nSaved to: {out}")
        except Exception as e:
            messagebox.showerror("Encoding failed", str(e))

    ttk.Button(frame, text="Encode", command=do_encode).grid(row=4, column=1, pady=10, sticky="w")

    ttk.Separator(frame, orient="horizontal").grid(row=5, column=0, columnspan=3, sticky="ew", pady=12)

    ttk.Label(frame, text="Decode: extract a hidden image from an audio file", font=("", 10, "bold")).grid(
        row=6, column=0, columnspan=3, sticky="w", pady=(0, 8)
    )
    dec_audio = path_row(frame, "Audio with hidden image:", 7, AUDIO_TYPES)
    dec_output = path_row(frame, "Save extracted image as:", 8, [("PNG image", "*.png")], save=True, default_ext=".png")

    def do_decode():
        audio_path = dec_audio.get().strip()
        out = dec_output.get().strip()
        if not audio_path or not out:
            messagebox.showwarning("Missing info", "Please provide an audio file and output path.")
            return
        try:
            decode_image_from_audio(audio_path, out)
            messagebox.showinfo("Success", f"Image extracted successfully.\nSaved to: {out}")
        except Exception as e:
            messagebox.showerror("Decoding failed", str(e))

    ttk.Button(frame, text="Decode", command=do_decode).grid(row=9, column=1, pady=10, sticky="w")

    root.mainloop()


if __name__ == "__main__":
    main()
