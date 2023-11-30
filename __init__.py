bl_info = {
    "name": "tts_client",
    "author": "reijaff",
    "description": "",
    "blender": (3, 4, 0),
    "version": (0, 3, 0),
    "location": "",
    "warning": "",
    "category": "Generic",
}

import subprocess
import requests
import hashlib
import base64
import threading
import asyncio
import shutil
import time
import aud
import sys
import os
import bpy
import json


transcription_cache = {}

wm = bpy.context.window_manager


def progress_func():
    tot = 100
    wm.progress_begin(0, tot)
    for i in range(tot):
        wm.progress_update(i)


class TtsClientAddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    tts_audio_project_folder: bpy.props.StringProperty(
        name="Folder name for TTS audio",
        description="Folder name for TTS audio in a specific folder alongside blend file",
        default="tts_audio",
    )

    tts_audio_preview_folder: bpy.props.StringProperty(
        name="Common folder path for TTS audio",
        description="Common folder path where TTS audio are stored",
        subtype="DIR_PATH",
        default=os.path.join(bpy.utils.user_resource("DATAFILES"), "tts_audio"),
    )


class TtsClientData(bpy.types.PropertyGroup):
    """Setting per Scene"""

    audio_is_playing: bpy.props.BoolProperty(description="Audio is playing")

    input_text: bpy.props.StringProperty(
        description="Text to synthesize", default="Everything is a test!"
    )

    add_transcription: bpy.props.BoolProperty(
        description="Add transcription", default=True
    )


def tts_output(audio_filepath):
    print("hello from tts_output")
    global pipe_client
    addon_prefs = bpy.context.preferences.addons[__package__].preferences
    addon_data = bpy.context.scene.tts_client_data

    addon_prefs.tts_server_status = "processing"
    payload = {
        "text": addon_data.input_text,
        "transcription": addon_data.add_transcription,
        # "speaker_id": addon_data.vctk_vits_speaker_idx,
    }
    ret = requests.get("http://127.0.0.1:5300/api/balacoon_tts", params=payload)
    addon_prefs.tts_server_status = "free"
    ret_data = ret.json()

    with open(audio_filepath, "wb") as f:
        f.write(base64.b64decode(ret_data["audio"]))

    return ret_data["transcription"]


class TTS_Audio_Add(bpy.types.Operator):
    bl_label = "Add"
    bl_idname = "tts_client.tts_audio_add"
    bl_description = "Add sound to the VSE at the current frame"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        pf1 = threading.Thread(target=progress_func, args=())
        pf1.start()

        addon_prefs = bpy.context.preferences.addons[__package__].preferences
        addon_data = bpy.context.scene.tts_client_data

        _input_text = bpy.context.scene.tts_client_data.input_text
        _preview_folder = addon_prefs.tts_audio_preview_folder

        if _input_text == "":
            self.report({"ERROR"}, "Input text is empty")
            return {"FINISHED"}

        if not bpy.data.is_saved:
            self.report({"ERROR"}, "Project is not saved")
            return {"FINISHED"}

        # algorithm for audio name
        audio_name = hashlib.md5(_input_text.encode("utf-8")).hexdigest() + ".wav"

        # create directory for audio
        folderpath = os.path.join(
            os.path.dirname(bpy.data.filepath), addon_prefs.tts_audio_project_folder
        )
        if not os.path.isdir(folderpath):
            os.makedirs(folderpath, exist_ok=True)
        audio_filepath = os.path.join(folderpath, audio_name)

        preview_filepath = os.path.join(_preview_folder, audio_name)

        if os.path.isfile(preview_filepath):
            shutil.copy(preview_filepath, audio_filepath)

        if not os.path.isfile(audio_filepath):
            transcription_cache[audio_name] = tts_output(audio_filepath)

        if not bpy.context.scene.sequence_editor:
            bpy.context.scene.sequence_editor_create()

        if not bpy.context.sequences:
            addSceneChannel = 1
        else:
            channels = [s.channel for s in bpy.context.sequences]
            channels = sorted(list(set(channels)))
            empty_channel = channels[-1] + 1
            addSceneChannel = empty_channel

        newStrip = bpy.context.scene.sequence_editor.sequences.new_sound(
            name=os.path.basename(audio_filepath),
            filepath=f"//{addon_prefs.tts_audio_project_folder}/{audio_name}",
            channel=addSceneChannel,
            frame_start=bpy.context.scene.frame_current,
        )
        newStrip.show_waveform = True
        newStrip.sound.use_mono = True

        # transcription = transcription_cache[audio_filepath]

        # if transcription:
        # print("add: ", transcription_cache)
        if audio_name in transcription_cache:
            framerate = bpy.context.scene.render.fps

            my_words = []
            for i in transcription_cache[audio_name]["segments"]:
                my_words += i["words"]

            for i in my_words:
                bpy.context.scene.timeline_markers.new(
                    name="{}".format(i["text"]),
                    frame=(
                        bpy.context.scene.frame_current + int(framerate * i["start"])
                    ),
                )

        wm.progress_end()

        # bpy.context.scene.sequence_editor.sequences_all[
        # newStrip.name
        # ].frame_start = bpy.context.scene.frame_current

        return {"FINISHED"}


class TTS_Audio_Play(bpy.types.Operator):
    bl_label = "Play"
    bl_idname = "tts_client.tts_audio_play"
    bl_description = "Play audio preview"
    bl_options = {"REGISTER", "UNDO"}
    handle = 0

    def execute(self, context):
        # progress from [0 - 1000]
        pf2 = threading.Thread(target=progress_func, args=())
        pf2.start()

        addon_prefs = bpy.context.preferences.addons[__package__].preferences
        addon_data = bpy.context.scene.tts_client_data
        _preview_folder = addon_prefs.tts_audio_preview_folder
        _input_text = bpy.context.scene.tts_client_data.input_text

        if _input_text == "":
            self.report({"ERROR"}, "Input text is empty")
            return {"FINISHED"}

        if not bpy.data.is_saved:
            self.report({"ERROR"}, "Project is not saved")
            return {"FINISHED"}

        # algorithm for audio name
        audio_name = hashlib.md5(_input_text.encode("utf-8")).hexdigest() + ".wav"

        # create directory for audio

        if not os.path.isdir(_preview_folder):
            os.makedirs(_preview_folder, exist_ok=True)
        audio_filepath = os.path.join(_preview_folder, audio_name)

        if not os.path.isfile(audio_filepath):
            transcription_cache[audio_name] = tts_output(audio_filepath)

        # print("add: ", transcription_cache)
        wm.progress_end()

        try:
            # Playing file audio_filepath
            addon_data.audio_is_playing = True
            device = aud.Device()
            audio = aud.Sound.file(audio_filepath)

            TTS_Audio_Play.handle = device.play(audio)
            TTS_Audio_Play.handle.loop_count = -1  # TODO

        except Exception as e:
            self.report({"WARNING"}, f"[Play] Error ... {e}")
            return {"CANCELLED"}

        return {"FINISHED"}


class TTS_Audio_Pause(bpy.types.Operator):
    bl_label = "Pause"
    bl_idname = "tts_client.tts_audio_pause"
    bl_description = "Pause audio preview"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        addon_data = context.scene.tts_client_data
        # if (addon_data.audio_loaded):
        addon_data.audio_is_playing = False
        TTS_Audio_Play.handle.stop()
        return {"FINISHED"}


class TTS_PT_Panel(bpy.types.Panel):
    bl_label = "Text To Speach"
    bl_space_type = "SEQUENCE_EDITOR"
    bl_region_type = "UI"
    bl_category = "TTS"

    @classmethod
    def poll(self, context):
        return context.space_data.view_type in {"SEQUENCER", "SEQUENCER_PREVIEW"}

    def draw(self, context):
        addon_prefs = bpy.context.preferences.addons[__package__].preferences

        # self.logger.info(f"docker access:{addon_prefs.docker_access}")
        # if not addon_prefs.docker_access:
        # col = self.layout.column(align=True)
        # col.label(text="Error accessing docker", icon="ERROR")
        # col.label(text="Check Addon Preferences")


class TTS_PT_subpanel_synthesize(bpy.types.Panel):
    bl_parent_id = "TTS_PT_Panel"
    bl_label = "Synthesize"

    bl_space_type = "SEQUENCE_EDITOR"
    bl_region_type = "UI"
    bl_category = "TTS"

    @classmethod
    def poll(cls, context):
        return True  # bpy.context.preferences.addons[__package__].preferences.docker_access

    def draw(self, context):
        addon_prefs = bpy.context.preferences.addons[__package__].preferences
        addon_data = context.scene.tts_client_data
        # if addon_prefs.docker_server_status != "on":
        # col = self.layout.column(align=True)
        # col.label(text="Error accessing docker server", icon="ERROR")
        # col.label(text="Launch docker server first")
        # else:

        col = self.layout.column(align=True)
        # col.scale_y = 2
        col.prop(addon_data, "input_text", text="", icon="RIGHTARROW")

        row = self.layout.row(align=True)
        if addon_data.audio_is_playing:
            row.operator("tts_client.tts_audio_pause", text="Pause", icon="PAUSE")
        else:
            row.operator("tts_client.tts_audio_play", text="Play", icon="PLAY_SOUND")

        row.operator("tts_client.tts_audio_add", text="Add", icon="NLA_PUSHDOWN")

        col = self.layout.column(align=True)
        col.prop(addon_data, "add_transcription", text="Transcription markers")


class TTS_PT_subpanel_settings(bpy.types.Panel):
    bl_parent_id = "TTS_PT_Panel"
    bl_label = "Scene Settings"

    bl_space_type = "SEQUENCE_EDITOR"
    bl_region_type = "UI"
    bl_category = "TTS"

    def draw(self, context):
        addon_data = context.scene.tts_client_data
        addon_prefs = bpy.context.preferences.addons[__package__].preferences

        col = self.layout.column(align=True)
        # col.operator("qnal.test_operator", text="test operator")
        # if addon_prefs.audacity_initialized:
        # col.prop(
        # addon_data,
        # "audacity_declicker",
        # text="Audacity De-Clicker",
        # toggle=True,
        # )
        # else:
        # col.label(text="Error accessing Audacity", icon="ERROR")
        # col.label(text="Setup Audacity Python API")

        box = self.layout.box()
        col = box.column()  # align=True)
        col.label(text="TTS server settings")

        row = col.row(align=True)
        # row.label(text="Docker server status:")
        # row.label(text=addon_prefs.docker_server_status)

        col.prop(addon_data, "model_name", text="Model")
        col.prop(addon_data, "vctk_vits_speaker_idx", text="Speaker id")

        # if addon_prefs.docker_server_status == "on":
        # col.operator("qnal.docker_stop",
        # text="Stop docker server", icon="PAUSE")
        # elif addon_prefs.docker_server_status == "loading ...":
        # col.label(text=addon_prefs.docker_server_status)
        # elif addon_prefs.docker_server_status == "off":
        # col.operator("qnal.docker_launch",
        # text="Launch docker server", icon="PLAY")


classes = [
    TtsClientAddonPreferences,
    TtsClientData,
    TTS_Audio_Play,
    TTS_Audio_Add,
    TTS_Audio_Pause,
    TTS_PT_Panel,
    TTS_PT_subpanel_synthesize,
    # TTS_PT_subpanel_settings,
]


def register():
    for c in classes:
        bpy.utils.register_class(c)

    bpy.types.Scene.tts_client_data = bpy.props.PointerProperty(type=TtsClientData)


def unregister():
    for c in classes[::-1]:
        bpy.utils.unregister_class(c)

