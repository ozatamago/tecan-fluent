"""Stand-ins for the Fluent PC and the FluentControl definitions, shared by the tests in features/ and io/."""

import hashlib

from unitelabs.tecan_fluent.apps.fluent780 import Fluent780ConnectorConfig, build_features


def vx(name, body):
    return (
        f"<VxData><Payload><ObjectName>{name}</ObjectName><PayloadData>{body}</PayloadData></Payload></VxData>".encode()
    )


LC_200 = (
    "<Tecan.Core.Pipetting.LiquidClassEquationSet><DeviceType><PipettingDeviceType>AirFca</PipettingDeviceType>"
    "</DeviceType><DiTiTypeGroup>FCA DiTi 200µl</DiTiTypeGroup><AspiratePipettingSpeed>150</AspiratePipettingSpeed>"
    "</Tecan.Core.Pipetting.LiquidClassEquationSet>"
)


class FakePc:
    files = {
        r"C\tip200.xcmp": vx(
            "FCA, 200ul SBS",
            "<Key>DiTiTypeGroup</Key><Value>FCA DiTi 200µl</Value>"
            "<Key>MaxNettoVolumeForTransferPhase</Key><Value>170</Value>",
        ),
        r"C\tip10.xcmp": vx(
            "FCA, 10ul SBS",
            "<Key>DiTiTypeGroup</Key><Value>FCA DiTi 10µl</Value>"
            "<Key>MaxNettoVolumeForTransferPhase</Key><Value>10</Value>",
        ),
        r"C\trough.xcmp": vx(
            "4 Well SBS Trough", "<XNumberOfWells>4</XNumberOfWells><YNumberOfWells>1</YNumberOfWells>"
        ),
        r"C\flat.xcmp": vx(
            "96 Well Flat_Custom", "<XNumberOfWells>12</XNumberOfWells><YNumberOfWells>8</YNumberOfWells>"
        ),
        r"C\pcr.xcmp": vx(
            "96 Well Skirted PCR_Custom", "<XNumberOfWells>12</XNumberOfWells><YNumberOfWells>8</YNumberOfWells>"
        ),
        r"L\wfs.xlqc": vx("Water Free Single", LC_200),
    }

    def index(self):
        return {
            p: {
                "path": p,
                "sha256": hashlib.sha256(d).hexdigest(),
                "name": d.decode().split("<ObjectName>")[1].split("<")[0],
            }
            for p, d in self.files.items()
        }

    def read(self, rel):
        return self.files[rel]


class _S:
    def update(self, *a, **k):
        pass


def _setup():
    f = {type(x).__name__: x for x in build_features(Fluent780ConnectorConfig())}  # dry run
    lh, lc, backend = f["LiquidHandling"], f["LabwareController"], f["RunController"].backend
    lh.pc = FakePc()
    return lh, lc, backend
