# Nagi / BRAT INTELLIGENCE
Brand guideline v3 — punk / manga-zine / developer culture.

## Concept
“Decisions with attitude.” Một công cụ kỹ thuật có cá tính tự tin, hơi ngang, ngắn gọn. Thông điệp mô tả giữ nguyên: “Typed decisions. Visible probabilities.”
Nagi là model family System One tự host, trả quyết định có kiểu và phân phối xác suất trên tập lựa chọn đóng. Choice / Score / Noul là ba primitive; Nagi-Smol, Nagi-Big, Nagi-Huge và Nagi-Enormous dùng chung nhận diện.

## Mascot nhân vật
Logo chủ đạo là mascot nữ chibi với tóc bob vàng ngắn bất đối xứng, hai kẹp đen điểm hồng, mắt xanh nửa khép và nụ cười tự tin. Jacket đen tối giản. Duy trì các nét này qua mọi hình ảnh.
Nguồn cảm hứng do chủ sản phẩm cung cấp: Nagi Sanzenin. Chỉ dùng liên tưởng màu sắc và thái độ; khuôn mặt, tóc ngắn và trang phục được thiết kế riêng. Không dùng khung truyện, costume hoặc logo của tác phẩm. Không tuyên bố có liên kết chính thức.
File mascot hiện là PNG, không phải vector. Dùng avatar từ 64 px trở lên; ở kích thước 16–32 px ưu tiên wordmark/ký tự n đơn giản cho đến khi có bản mascot rút gọn. Không thêm texture lên mắt và miệng. Không kéo giãn hoặc đổi biểu cảm giữa các ứng dụng chính.

## Màu
Ink #111114: nền chính, khoảng 65% layout marketing.
Bone #F3EEDB: chữ, giấy, khoảng 20%.
Acid yellow #F5E642: CTA/tape/ribbon, khoảng 10%.
Emerald #36D988: lựa chọn active và điểm nhấn.
Hot pink #FF4D94: dấu ấn và print offset, dùng tiết chế.
Muted #B7B4AC: chữ phụ. Line #48484D: đường chia phi tương tác.
Dùng bone trên ink; ink trên yellow/green/pink. Không dùng bone trên yellow/pink cho body. Selected luôn kèm chữ hoặc icon, không chỉ đổi màu.

## Logo lockup
Mascot là nhận diện chính; wordmark nagi đi kèm trong header hoặc banner. Khoảng cách giữa mascot và wordmark tối thiểu 1/4 chiều cao mascot. Không sử dụng emblem hình học từ các bản trước.
Giữ clear space 1/8 chiều rộng mascot. Wordmark SVG là bản gọn cho UI; lettering raster trong banner là bản campaign. Nền đen phù hợp nhất với tài sản hiện tại; không giả định PNG có nền trong suốt.

## Typography
Display: condensed heavy, ưu tiên Impact với fallback Arial Narrow/sans; headline nghiêng nhẹ, viết hoa, tracking -0.03em. Body: Inter/system-ui. Code/data: IBM Plex Mono/ui-monospace. Font không được đóng gói.
Desktop display 72–104 px / 0.95; mobile 40–56 px / 1.0. Body 16/24; label 12/18. Giữ nghiêng và biến dạng ở headline/artwork, không áp dụng bảng dữ liệu và code.

## Graphic grammar
Cắt chéo 8–12°, cạnh vuông, đường kẻ rõ, một yellow tape hoặc pink stamp mỗi bố cục. Grain/halftone chỉ trên artwork, không phủ chữ nhỏ hay vùng dữ liệu. Tránh texture dày làm mất tương phản.
Dùng nhiều khoảng trống đen để bố cục có chủ đích. Không dùng gradient mềm, ceramic 3D, bo tròn pill hàng loạt hoặc neon glow.

## Product UI
Marketing được mạnh; màn hình sản phẩm ưu tiên đọc được. Nền ink, panel #1C1C21, chữ bone; border control #B7B4AC. Primary CTA yellow/ink, cao tối thiểu 44 px, radius 0; hover bone/ink. Focus outline green 2 px, offset 3 px. Button phụ ink/bone với border muted. Disabled ghi rõ trạng thái và chặn thao tác.
Decision card: câu hỏi → nhãn lựa chọn → quyết định → phân phối. Xác suất dùng mono, thanh cùng thang 0–1. Không dùng icon crown cho chất lượng model hoặc nhầm confidence với accuracy.
Error có nhãn và hướng xử lý, dùng pink + chữ; success dùng green + nhãn. Loading: “Đang đánh giá các lựa chọn…”. Empty state có ví dụ input và CTA.
Motion 100–160 ms; chỉ microinteraction. Không glitch nhấp nháy; tôn trọng reduced-motion. Spacing 4/8/12/16/24/32/48/64/96; content width 1120 px; lề mobile 20 px.

## Voice
Tự tin, sắc, ít chữ; không công kích người dùng. Campaign: “Decisions with attitude.” Mô tả kỹ thuật: “Typed decisions. Visible probabilities.” CTA: “Run Nagi”, “See the distribution”, “Read the docs”.
Không quảng cáo xác suất là bảo đảm đúng; không đưa benchmark/tốc độ thiếu điều kiện đo. Không tự hứa khả năng sinh văn bản.

## Banner
Banner 2:1 cho README/hero, typography trái và mascot phải. Dùng đúng tỷ lệ gốc, không crop mất headline; trên mobile dùng contain hoặc tách text khỏi artwork. Nếu làm social 1200×630, bố trí lại thay vì kéo ảnh.
Tài sản raster tạo bằng ImageGen tích hợp; prompt nằm trong image-prompts.txt. Bộ v3 thay thế logo hình học của các bản trước; Bộ tài sản được lưu trong `docs/brand`; banner được sử dụng trong README.
