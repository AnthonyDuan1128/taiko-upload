import os
from datetime import datetime, timezone
from flask import (Flask, render_template, redirect, url_for, flash,
                   request, abort, send_from_directory, jsonify)
from flask_login import (LoginManager, login_user, logout_user,
                         login_required, current_user)
from werkzeug.utils import secure_filename

from flask_wtf.csrf import CSRFProtect

from config import Config
from models import db, User, Submission, Comment, Like
from forms import RegistrationForm, LoginForm, UploadForm, CommentForm
from utils import filter_sensitive_words, upload_to_taiko_server, ensure_upload_dir


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Ensure upload folder exists
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    # Init extensions
    db.init_app(app)
    CSRFProtect(app)

    login_manager = LoginManager()
    login_manager.login_view = 'login'
    login_manager.login_message = '请先登录'
    login_manager.login_message_category = 'warning'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # ── Create tables & default admin ────────────────────────────────────
    with app.app_context():
        db.create_all()
        admin_user = os.environ.get('ADMIN_USERNAME', 'admin')
        admin_pass = os.environ.get('ADMIN_PASSWORD', 'admin123')
        if not User.query.filter_by(is_admin=True).first():
            admin = User(username=admin_user, email='admin@taiko.local', is_admin=True)
            admin.set_password(admin_pass)
            db.session.add(admin)
            db.session.commit()

    # ── Context processor ────────────────────────────────────────────────
    @app.context_processor
    def inject_now():
        return {'now': datetime.now(timezone.utc)}

    # ── Routes ───────────────────────────────────────────────────────────

    @app.route('/')
    def index():
        return redirect(url_for('community'))

    # ── Auth ─────────────────────────────────────────────────────────────

    @app.route('/register', methods=['GET', 'POST'])
    def register():
        if current_user.is_authenticated:
            return redirect(url_for('dashboard'))
        form = RegistrationForm()
        if form.validate_on_submit():
            user = User(username=form.username.data, email=form.email.data)
            user.set_password(form.password.data)
            db.session.add(user)
            db.session.commit()
            flash('注册成功！请登录。', 'success')
            return redirect(url_for('login'))
        return render_template('register.html', form=form)

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for('dashboard'))
        form = LoginForm()
        if form.validate_on_submit():
            user = User.query.filter_by(username=form.username.data).first()
            if user and user.check_password(form.password.data):
                login_user(user)
                flash('登录成功！', 'success')
                next_page = request.args.get('next', '')
                # Prevent open redirect: only allow relative paths
                if not next_page or not next_page.startswith('/'):
                    next_page = url_for('dashboard')
                return redirect(next_page)
            flash('用户名或密码错误', 'danger')
        return render_template('login.html', form=form)

    @app.route('/logout')
    @login_required
    def logout():
        logout_user()
        flash('已退出登录', 'info')
        return redirect(url_for('community'))

    # ── Upload ───────────────────────────────────────────────────────────

    @app.route('/upload', methods=['GET', 'POST'])
    @login_required
    def upload():
        form = UploadForm()
        if form.validate_on_submit():
            try:
                # Create submission record first to get ID
                submission = Submission(
                    user_id=current_user.id,
                    title=form.title.data.strip(),
                    artist=form.artist.data.strip() if form.artist.data else '',
                    song_type=form.song_type.data,
                    tja_filename='',
                    ogg_filename='',
                )
                db.session.add(submission)
                db.session.flush()  # Get ID

                # Save files in per-submission directory
                upload_dir = ensure_upload_dir(app.config['UPLOAD_FOLDER'], submission.id)

                tja = form.tja_file.data
                ogg = form.ogg_file.data
                # secure_filename may return '' for CJK-only filenames
                tja_name = secure_filename(tja.filename)
                if not tja_name or not tja_name.lower().endswith('.tja'):
                    tja_name = f'{submission.id}.tja'
                ogg_name = secure_filename(ogg.filename)
                if not ogg_name or not ogg_name.lower().endswith('.ogg'):
                    ogg_name = f'{submission.id}.ogg'

                tja.save(os.path.join(upload_dir, tja_name))
                ogg.save(os.path.join(upload_dir, ogg_name))

                submission.tja_filename = tja_name
                submission.ogg_filename = ogg_name
                db.session.commit()

                flash('投稿成功！等待管理员审核。', 'success')
                return redirect(url_for('dashboard'))
            except Exception as e:
                db.session.rollback()
                app.logger.error(f'Upload failed: {e}')
                flash('上传失败，请重试。', 'danger')
        return render_template('upload.html', form=form)

    # ── Dashboard ────────────────────────────────────────────────────────

    @app.route('/dashboard')
    @login_required
    def dashboard():
        page = request.args.get('page', 1, type=int)
        submissions = Submission.query.filter_by(user_id=current_user.id) \
            .order_by(Submission.created_at.desc()) \
            .paginate(page=page, per_page=10, error_out=False)
        return render_template('dashboard.html', submissions=submissions)

    @app.route('/cancel/<int:sid>', methods=['POST'])
    @login_required
    def cancel_submission(sid):
        sub = db.session.get(Submission, sid)
        if sub is None:
            abort(404)
        if sub.user_id != current_user.id:
            abort(403)
        if sub.status != Submission.STATUS_PENDING:
            flash('只能取消审核中的投稿', 'warning')
            return redirect(url_for('dashboard'))
        sub.status = Submission.STATUS_CANCELLED
        db.session.commit()
        flash('投稿已取消', 'info')
        return redirect(url_for('dashboard'))

    # ── Community ────────────────────────────────────────────────────────

    @app.route('/community')
    def community():
        page = request.args.get('page', 1, type=int)
        submissions = Submission.query.filter_by(status=Submission.STATUS_APPROVED) \
            .order_by(Submission.reviewed_at.desc()) \
            .paginate(page=page, per_page=12, error_out=False)
        return render_template('community.html', submissions=submissions)

    @app.route('/submission/<int:sid>')
    def submission_detail(sid):
        sub = db.session.get(Submission, sid)
        if sub is None:
            abort(404)
        # Only show approved submissions to non-owners/non-admin
        if sub.status != Submission.STATUS_APPROVED:
            if not current_user.is_authenticated:
                abort(404)
            if not current_user.is_admin and sub.user_id != current_user.id:
                abort(404)
        form = CommentForm()
        comments = sub.comments.order_by(Comment.created_at.desc()).all()
        user_liked = False
        if current_user.is_authenticated:
            user_liked = Like.query.filter_by(
                user_id=current_user.id, submission_id=sid
            ).first() is not None
        return render_template('submission_detail.html',
                               submission=sub, form=form,
                               comments=comments, user_liked=user_liked)

    @app.route('/like/<int:sid>', methods=['POST'])
    @login_required
    def toggle_like(sid):
        sub = db.session.get(Submission, sid)
        if sub is None:
            abort(404)
        if sub.status != Submission.STATUS_APPROVED:
            abort(404)
        existing = Like.query.filter_by(
            user_id=current_user.id, submission_id=sid
        ).first()
        if existing:
            db.session.delete(existing)
            db.session.commit()
            liked = False
        else:
            like = Like(user_id=current_user.id, submission_id=sid)
            db.session.add(like)
            db.session.commit()
            liked = True
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'liked': liked, 'count': sub.like_count})
        return redirect(url_for('submission_detail', sid=sid))

    @app.route('/comment/<int:sid>', methods=['POST'])
    @login_required
    def add_comment(sid):
        sub = db.session.get(Submission, sid)
        if sub is None:
            abort(404)
        if sub.status != Submission.STATUS_APPROVED:
            abort(404)
        form = CommentForm()
        if form.validate_on_submit():
            filtered = filter_sensitive_words(form.content.data.strip())
            comment = Comment(
                user_id=current_user.id,
                submission_id=sid,
                content=filtered,
            )
            db.session.add(comment)
            db.session.commit()
            flash('评论发表成功', 'success')
        return redirect(url_for('submission_detail', sid=sid))

    # ── Admin ────────────────────────────────────────────────────────────

    @app.route('/1128admin1128')
    @login_required
    def admin_panel():
        if not current_user.is_admin:
            abort(403)
        tab = request.args.get('tab', 'pending')
        page = request.args.get('page', 1, type=int)
        if tab == 'approved':
            q = Submission.query.filter_by(status=Submission.STATUS_APPROVED)
        elif tab == 'rejected':
            q = Submission.query.filter_by(status=Submission.STATUS_REJECTED)
        else:
            q = Submission.query.filter_by(status=Submission.STATUS_PENDING)
            tab = 'pending'
        submissions = q.order_by(Submission.created_at.desc()) \
            .paginate(page=page, per_page=20, error_out=False)
        return render_template('admin.html', submissions=submissions, tab=tab)

    @app.route('/1128admin1128/review/<int:sid>', methods=['POST'])
    @login_required
    def admin_review(sid):
        if not current_user.is_admin:
            abort(403)
        sub = db.session.get(Submission, sid)
        if sub is None:
            abort(404)
        if sub.status != Submission.STATUS_PENDING:
            flash('该投稿不在审核中状态', 'warning')
            return redirect(url_for('admin_panel'))

        # Parse form fields directly (admin template uses raw HTML form)
        action = request.form.get('action', '')
        review_note = request.form.get('review_note', '')

        if action not in ('approve', 'reject'):
            flash('无效的审核操作', 'danger')
            return redirect(url_for('admin_panel'))

        sub.review_note = review_note
        sub.reviewed_at = datetime.now(timezone.utc)

        if action == 'approve':
            # Try uploading to taiko.asia
            upload_dir = os.path.join(app.config['UPLOAD_FOLDER'], str(sub.id))
            tja_path = os.path.join(upload_dir, sub.tja_filename)
            ogg_path = os.path.join(upload_dir, sub.ogg_filename)

            if not os.path.isfile(tja_path) or not os.path.isfile(ogg_path):
                flash('投稿文件丢失，无法上传', 'danger')
                return redirect(url_for('admin_panel'))

            ok, msg = upload_to_taiko_server(
                tja_path, ogg_path, sub.song_type,
                app.config['TAIKO_SERVER_URL'],
                app.config['USE_PROXY'],
                app.config.get('PROXY_URL'),
            )
            if ok:
                sub.status = Submission.STATUS_APPROVED
                flash(f'投稿 "{sub.title}" 已通过并上传到服务器', 'success')
            else:
                flash(f'上传到服务器失败: {msg}。投稿保持审核中状态。', 'danger')
                return redirect(url_for('admin_panel'))
        else:
            sub.status = Submission.STATUS_REJECTED
            flash(f'投稿 "{sub.title}" 已拒绝', 'info')

        db.session.commit()
        return redirect(url_for('admin_panel'))

    @app.route('/1128admin1128/preview/<int:sid>/<path:filename>')
    @login_required
    def admin_preview_file(sid, filename):
        if not current_user.is_admin:
            abort(403)
        upload_dir = os.path.join(app.config['UPLOAD_FOLDER'], str(sid))
        return send_from_directory(upload_dir, filename)

    return app


# ── Entry point ──────────────────────────────────────────────────────────
app = create_app()

if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.1', port=5000)
