"""Feature for the deck-check cameras of the Fluent 780 (the driver is in io/deck_cameras.py)."""

from unitelabs.cdk import sila

from ..io.deck_cameras import CameraFailed, DeckCameras


class DeckCamera(sila.Feature):
    """
    Images and video of the Fluent 780 deck from the three deck-check cameras (Left, Center, Right). Nothing moves and
    FluentControl is not used. Everything is saved on the Fluent PC with the records.

    Center is a wide-angle view of the whole deck; Left and Right show each half more closely. The arms can hide part
    of the view (for example, Left is hidden when the arms are parked on the left).

    Video runs in the background (StartRecording ... StopRecording), also while other commands move the instrument.
    Images can be taken while recording.
    """

    def __init__(self, cameras: DeckCameras):
        super().__init__(originator="jp.riken.bdr", category="fluent", version="1.0")
        self.cameras = cameras

    @sila.UnobservableProperty()
    async def get_cameras(self) -> list[str]:
        """The camera names, e.g. "Center"."""
        return list(self.cameras.config.cameras)

    @sila.ObservableCommand(errors=[CameraFailed])
    async def take_image(self, camera: str, *, status: sila.Status) -> tuple[str, bytes]:
        """
        Take one image with one camera and save it on the Fluent PC. Works while recording too.

        Args:
          Camera: "Left", "Center" or "Right".

        Returns:
          ImagePath: Where the full-size PNG (3072 x 2048) is saved on the Fluent PC.
          Preview: A smaller JPEG (1280 px wide) of the same image.
        """
        import asyncio

        try:
            [r] = await asyncio.to_thread(self.cameras.capture, [camera], self.cameras.single_dir())
            if r["status"] != "ok":
                raise CameraFailed(r.get("error") or r["status"])
            return r["image"], await asyncio.to_thread(self.cameras.preview, r["preview"])
        except CameraFailed:
            raise
        except Exception as exc:  # noqa: BLE001
            raise CameraFailed(f"{type(exc).__name__}: {exc}") from None

    @sila.ObservableCommand(errors=[CameraFailed])
    async def take_all_images(self, *, status: sila.Status) -> list[str]:
        """
        Take one image with each camera and save them on the Fluent PC. Works while recording too.

        Returns:
          ImagePaths: Where the PNGs are saved, or an error per camera that failed.
        """
        import asyncio

        try:
            results = await asyncio.to_thread(
                self.cameras.capture, list(self.cameras.config.cameras), self.cameras.single_dir()
            )
        except Exception as exc:  # noqa: BLE001
            raise CameraFailed(str(exc)) from None
        return [r.get("image") or f"{r['camera']}: {r.get('error') or r['status']}" for r in results]

    @sila.ObservableCommand(errors=[CameraFailed])
    async def start_recording(self, cameras: list[str], frames_per_second: float, *, status: sila.Status) -> str:
        """
        Start recording video with the given cameras and return at once; the video goes on in the background until
        StopRecording (at most 30 minutes). Other commands, including ones that move the instrument, can run meanwhile.

        Args:
          Cameras: Cameras to record, e.g. ["Left", "Center", "Right"] or ["Center"].
          FramesPerSecond: Frames per second per camera, or 0 for as many as possible (about 2 with three cameras,
            3 with two; the cameras share one network link and are read one after another).

        Returns:
          Folder: Where the video is saved on the Fluent PC (inside the open run's record if a run is open).
        """
        import asyncio

        try:
            return await asyncio.to_thread(self.cameras.start_recording, list(cameras), float(frames_per_second))
        except CameraFailed:
            raise
        except Exception as exc:  # noqa: BLE001
            raise CameraFailed(f"{type(exc).__name__}: {exc}") from None

    @sila.ObservableCommand(errors=[CameraFailed])
    async def stop_recording(self, *, status: sila.Status) -> list[str]:
        """
        Stop the video and save one MP4 per camera on the Fluent PC (this takes a little while: the frames are joined
        into a video).

        Returns:
          Videos: Where each camera's video.mp4 is saved, or why a camera has none.
        """
        import asyncio

        try:
            results = await asyncio.to_thread(self.cameras.stop_recording)
        except CameraFailed:
            raise
        except Exception as exc:  # noqa: BLE001
            raise CameraFailed(f"{type(exc).__name__}: {exc}") from None
        return [r.get("video") or f"{r['camera']}: {r['status']}" for r in results]

    @sila.UnobservableProperty()
    async def get_recording(self) -> str:
        """What is being recorded (cameras, start time and folder on the Fluent PC), or empty when not recording."""
        import asyncio

        rec = await asyncio.to_thread(self.cameras.recorder)
        return f"{', '.join(rec['record'])} since {rec['started']} into {rec['out_dir']}" if rec else ""
