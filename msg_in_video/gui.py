"""Standalone GUI: hide/extract a text message in a video."""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from stego import encode_message_in_video, decode_message_from_video

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


def main():
    root = tk.Tk()
    root.title("Message <-> Video")
    root.geometry("660x520")
    frame = ttk.Frame(root, padding=10)
    frame.pack(fill="both", expand=True)

    note = ("Note: output is always saved as a lossless FFV1 .avi file -- "
            "any other format/codec would destroy the hidden bits.")

    ttk.Label(frame, text="Encode: hide a text message inside a video", font=("", 10, "bold")).grid(
        row=0, column=0, columnspan=3, sticky="w", pady=(0, 8)
    )
    enc_input = path_row(frame, "Source video:", 1, VIDEO_TYPES)
    ttk.Label(frame, text="Message:").grid(row=2, column=0, sticky="nw", padx=5, pady=4)
    enc_message = tk.Text(frame, width=55, height=5)
    enc_message.grid(row=2, column=1, columnspan=2, padx=5, pady=4, sticky="w")
    enc_output = path_row(frame, "Save output video as:", 3, [("AVI video", "*.avi")], save=True, default_ext=".avi")
    ttk.Label(frame, text=note, foreground="#555", wraplength=560, justify="left").grid(
        row=4, column=0, columnspan=3, sticky="w", padx=5
    )

    def do_encode():
        src = enc_input.get().strip()
        out = enc_output.get().strip()
        message = enc_message.get("1.0", tk.END).rstrip("\n")
        if not src or not out or not message:
            messagebox.showwarning("Missing info", "Please provide a source video, message, and output path.")
            return
        try:
            saved_to = encode_message_in_video(src, message, out)
            messagebox.showinfo("Success", f"Message embedded successfully.\nSaved to: {saved_to}")
        except Exception as e:
            messagebox.showerror("Encoding failed", str(e))

    ttk.Button(frame, text="Encode", command=do_encode).grid(row=5, column=1, pady=10, sticky="w")

    ttk.Separator(frame, orient="horizontal").grid(row=6, column=0, columnspan=3, sticky="ew", pady=12)

    ttk.Label(frame, text="Decode: extract a hidden text message from a video", font=("", 10, "bold")).grid(
        row=7, column=0, columnspan=3, sticky="w", pady=(0, 8)
    )
    dec_input = path_row(frame, "Video with hidden message:", 8, VIDEO_TYPES)
    dec_output = tk.Text(frame, width=55, height=5)

    def do_decode():
        src = dec_input.get().strip()
        if not src:
            messagebox.showwarning("Missing info", "Please select a video.")
            return
        try:
            message = decode_message_from_video(src)
            dec_output.delete("1.0", tk.END)
            dec_output.insert(tk.END, message)
        except Exception as e:
            messagebox.showerror("Decoding failed", str(e))

    ttk.Button(frame, text="Decode", command=do_decode).grid(row=9, column=1, pady=10, sticky="w")
    ttk.Label(frame, text="Decoded message:").grid(row=10, column=0, sticky="nw", padx=5, pady=4)
    dec_output.grid(row=10, column=1, columnspan=2, padx=5, pady=4, sticky="w")

    root.mainloop()


if __name__ == "__main__":
    main()
