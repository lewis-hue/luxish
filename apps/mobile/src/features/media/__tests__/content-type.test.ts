import { contentTypeFor } from '@/features/media/upload';

describe('contentTypeFor', () => {
  it('still reads a camera roll photograph correctly', () => {
    expect(contentTypeFor('file:///x/IMG_1.jpg')).toBe('image/jpeg');
    expect(contentTypeFor('file:///x/a.png')).toBe('image/png');
    expect(contentTypeFor('file:///x/a.HEIC')).toBe('image/heic');
  });

  it('reads a video as a video', () => {
    // Everything used to fall through to `image/jpeg`, so a video
    // was uploaded as a photograph and the thread then tried to
    // draw it as one.
    expect(contentTypeFor('file:///x/clip.mp4')).toBe('video/mp4');
    expect(contentTypeFor('file:///x/clip.MOV')).toBe('video/quicktime');
  });

  it('reads a voice note as sound', () => {
    expect(contentTypeFor('file:///x/note.m4a')).toBe('audio/m4a');
    expect(contentTypeFor('file:///x/note.caf')).toBe('audio/x-caf');
  });

  it('ignores a query string on the path', () => {
    expect(contentTypeFor('file:///x/clip.mp4?t=1')).toBe('video/mp4');
  });

  it('falls back to a photograph for something unrecognised', () => {
    // The commonest thing by far, and the server validates the bytes
    // regardless.
    expect(contentTypeFor('file:///x/nameless')).toBe('image/jpeg');
  });
});
