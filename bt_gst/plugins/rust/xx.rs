use gst::glib;
use gst::prelude::*;
use gst_base::subclass::prelude::*;
use gst::subclass::prelude::*;

const H264_CAPS: &str = "video/x-h264,stream-format=byte-stream,alignment=au";
const UUID: &[u8; 16] = b"BTGSTSEI01234567";

mod imp {
    use super::*;
    use std::sync::LazyLock;

    #[derive(Default)]
    pub struct BtH264Sei;

    #[glib::object_subclass]
    impl ObjectSubclass for BtH264Sei {
        const NAME: &'static str = "BtH264Sei";
        type Type = super::BtH264Sei;
        type ParentType = gst_base::BaseTransform;
    }

    impl ObjectImpl for BtH264Sei {}

    impl GstObjectImpl for BtH264Sei {}

    impl ElementImpl for BtH264Sei {
        fn metadata() -> Option<&'static gst::subclass::ElementMetadata> {
            static METADATA: LazyLock<gst::subclass::ElementMetadata> = LazyLock::new(|| {
                gst::subclass::ElementMetadata::new(
                    "BT H264 SEI",
                    "Filter/Video",
                    "Injects user_data_unregistered SEI into H.264 access units",
                    "bt_ws",
                )
            });

            Some(&*METADATA)
        }

        fn pad_templates() -> &'static [gst::PadTemplate] {
            static TEMPLATES: LazyLock<Vec<gst::PadTemplate>> = LazyLock::new(|| {
                let caps = gst::Caps::from_string(H264_CAPS).unwrap();

                vec![
                    gst::PadTemplate::new(
                        "src",
                        gst::PadDirection::Src,
                        gst::PadPresence::Always,
                        &caps,
                    )
                    .unwrap(),
                    gst::PadTemplate::new(
                        "sink",
                        gst::PadDirection::Sink,
                        gst::PadPresence::Always,
                        &caps,
                    )
                    .unwrap(),
                ]
            });

            TEMPLATES.as_ref()
        }
    }

    impl BaseTransformImpl for BtH264Sei {
        const MODE: gst_base::subclass::BaseTransformMode =
            gst_base::subclass::BaseTransformMode::NeverInPlace;

        fn prepare_output_buffer(
            &self,
            input: &gst::Buffer,
        ) -> Result<gst::Buffer, gst::FlowError> {
            let map = input.map_readable().map_err(|_| gst::FlowError::Error)?;
            let data = map.as_slice();

            let insert_at = first_vcl_start(data).unwrap_or(0);
            let sei = make_user_data_unregistered_sei(build_payload(input).as_bytes());

            let mut output = gst::Buffer::new();

            if insert_at > 0 {
                let prefix = input.copy_region(
                    gst::BufferCopyFlags::MEMORY,
                    0,
                    Some(insert_at),
                )
                .map_err(|_| gst::FlowError::Error)?;

                append_buffer_memory(&mut output, prefix)?;
            }

            output.append_memory(gst::Memory::from_slice(sei));

            let suffix_len = data.len() - insert_at;
            if suffix_len > 0 {
                let suffix = input.copy_region(
                    gst::BufferCopyFlags::MEMORY,
                    insert_at,
                    Some(suffix_len),
                )
                .map_err(|_| gst::FlowError::Error)?;

                append_buffer_memory(&mut output, suffix)?;
            }

            {
                let out = output.get_mut().ok_or(gst::FlowError::Error)?;
                out.set_pts(input.pts());
                out.set_dts(input.dts());
                out.set_duration(input.duration());
                out.set_offset(input.offset());
                out.set_offset_end(input.offset_end());
                out.set_flags(input.flags());
            }

            Ok(output)
        }

        fn transform(
            &self,
            _input: &gst::Buffer,
            _output: &mut gst::BufferRef,
        ) -> Result<gst::FlowSuccess, gst::FlowError> {
            Ok(gst::FlowSuccess::Ok)
        }
    }

    fn append_buffer_memory(
        output: &mut gst::Buffer,
        source: gst::Buffer,
    ) -> Result<(), gst::FlowError> {
        let out = output.get_mut().ok_or(gst::FlowError::Error)?;

        for index in 0..source.n_memory() {
            let memory = source.peek_memory(index).ok_or(gst::FlowError::Error)?;
            out.append_memory(memory.share(0, None));
        }

        Ok(())
    }
}

glib::wrapper! {
    pub struct BtH264Sei(ObjectSubclass<imp::BtH264Sei>)
        @extends gst_base::BaseTransform, gst::Element, gst::Object;
}

fn plugin_init(plugin: &gst::Plugin) -> Result<(), glib::BoolError> {
    gst::Element::register(
        Some(plugin),
        "bt_h264_sei",
        gst::Rank::NONE,
        BtH264Sei::static_type(),
    )
}

gst::plugin_define!(
    bt_h264_sei,
    env!("CARGO_PKG_DESCRIPTION"),
    plugin_init,
    env!("CARGO_PKG_VERSION"),
    "MIT/X11",
    env!("CARGO_PKG_NAME"),
    env!("CARGO_PKG_NAME"),
    "bt_ws",
    "2026-06-15"
);